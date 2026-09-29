#!/usr/bin/env python3
"""패킷 한 개를 계층별로 벗겨 낸다. 01부터 05까지를 하나로 잇는 마무리다.

API 호출 한 줄이 네트워크에서 어떤 모습이 되는지 끝까지 따라간다. 위에서 아래로
내려가며 계층마다 헤더가 덧붙는 것을 인캡슐레이션이라고 한다.

    [ 개발자가 부른 API ]          client.get()
             │
             ▼  애플리케이션 계층이 규약대로 적는다
    ┌────────────────────────────────────────┐
    │ HTTP: GET /sensors... 또는 MQTT PUBLISH │   ← 여기까지가 04, 05 폴더
    └────────────────────────────────────────┘
             │
             ▼  전송 계층이 포트와 순서 번호를 붙인다
    ┌──────────┬─────────────────────────────┐
    │ TCP 헤더 │      애플리케이션 바이트     │   ← 03 폴더
    └──────────┴─────────────────────────────┘
             │
             ▼  인터넷 계층이 주소를 붙인다
    ┌─────────┬──────────┬────────────────────┐
    │ IP 헤더 │ TCP 헤더 │  애플리케이션      │   ← 02 폴더
    └─────────┴──────────┴────────────────────┘
             │
             ▼  링크 계층이 MAC 주소를 붙인다
    ┌──────────┬─────────┬──────────┬─────────┐
    │ 이더넷   │ IP      │ TCP      │ 앱      │   ← 01 폴더
    └──────────┴─────────┴──────────┴─────────┘

    python3 ../tools/make_sample_pcap.py samples/sample.pcap
    python3 peel.py samples/sample.pcap
    python3 peel.py samples/sample.pcap -n 5 --hex
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.hexdump import annotate, hexdump, ipv4, mac  # noqa: E402
from tools.pcap import LINK_HEADER_LEN, PcapError, PcapFile, strip_link_header  # noqa: E402

PROTOCOLS = {1: "ICMP", 6: "TCP", 17: "UDP"}
FLAG_NAMES = [(0x02, "SYN"), (0x10, "ACK"), (0x01, "FIN"), (0x04, "RST"), (0x08, "PSH")]


def guess_app(sport, dport, payload):
    """포트와 첫 바이트로 애플리케이션 프로토콜을 짐작한다."""
    ports = {sport, dport}
    if payload[:4] in (b"GET ", b"PUT ", b"POST", b"HTTP") or ports & {80, 8080, 8000, 9200}:
        return "HTTP"
    if ports & {1883}:
        return "MQTT"
    if ports & {5683}:
        return "CoAP"
    if ports & {53}:
        return "DNS"
    return None


def describe_app(name, payload):
    """애플리케이션 계층 바이트를 한 줄로 풀어 준다."""
    if not payload:
        return "(본문 없음 — 제어용 세그먼트다)"
    if name == "HTTP":
        first = payload.split(b"\r\n", 1)[0].decode("latin-1")
        head_end = payload.find(b"\r\n\r\n")
        head = head_end + 4 if head_end >= 0 else len(payload)
        return f"{first}   (헤더 {head}바이트 + 본문 {len(payload) - head}바이트)"
    if name == "MQTT":
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                               / "04-application" / "mqtt"))
        import mqtt
        msg, _ = mqtt.decode(payload)
        if not msg:
            return f"(MQTT 패킷이 아직 다 오지 않았다, {len(payload)}바이트)"
        if msg["type"] == mqtt.PUBLISH:
            return (f"{msg['name']} 주제={msg['topic']!r} 값={msg['payload'].decode()!r} "
                    f"(MQTT 헤더 {msg['size'] - len(msg['payload'])} + 값 {len(msg['payload'])})")
        return f"{msg['name']} ({msg['size']}바이트)"
    return f"{len(payload)}바이트"


def main():
    ap = argparse.ArgumentParser(description="패킷을 계층별로 벗겨 낸다")
    ap.add_argument("pcap")
    ap.add_argument("-n", "--number", type=int, default=0,
                    help="몇 번째 패킷을 볼지 (0이면 본문이 있는 첫 패킷)")
    ap.add_argument("--hex", action="store_true", help="16진수 덤프도 찍는다")
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    chosen = None
    with f:
        for index, (ts, data, orig_len) in enumerate(f, start=1):
            if args.number and index != args.number:
                continue
            link_len, ip_pkt, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800 or len(ip_pkt) < 20 or ip_pkt[9] != 6:
                continue
            ihl = (ip_pkt[0] & 0x0F) * 4
            total_len = struct.unpack("!H", ip_pkt[2:4])[0]
            seg = ip_pkt[ihl:total_len]
            tcp_hlen = (struct.unpack("!H", seg[12:14])[0] >> 12) * 4
            payload = seg[tcp_hlen:]
            if args.number or payload:
                chosen = (index, ts, data, link_len, ip_pkt, ihl, seg, tcp_hlen, payload)
                break

    if not chosen:
        print("벗겨 볼 TCP 패킷을 찾지 못했다.", file=sys.stderr)
        return 1

    index, ts, data, link_len, ip_pkt, ihl, seg, tcp_hlen, payload = chosen
    sport, dport = struct.unpack("!HH", seg[:4])
    app = guess_app(sport, dport, payload)

    print("=" * 74)
    print(f"{index}번째 프레임 — 전체 {len(data)}바이트")
    print("=" * 74)
    print()

    # ── 1층 ──────────────────────────────────────────────────────────
    print(f"1층. 네트워크 인터페이스 — {f.linktype_name}, {link_len}바이트")
    if f.linktype_name == "EN10MB":
        print(annotate(data, [("목적지 MAC", 0, 6), ("출발지 MAC", 6, 6), ("이더타입", 12, 2)]))
        print(f"      {mac(data[6:12])} → {mac(data[0:6])}, 다음은 IPv4")
    else:
        print(f"      이더넷이 아니다. {f.linktype_name} 은 헤더가 {link_len}바이트다.")
    if args.hex and link_len:
        print(hexdump(data[:link_len]))
    print(f"      벗기면 남는 것: {len(data) - link_len}바이트")
    print()

    # ── 2층 ──────────────────────────────────────────────────────────
    print(f"2층. 인터넷 — IPv4, {ihl}바이트")
    print(annotate(ip_pkt, [("버전+IHL", 0, 1), ("전체 길이", 2, 2), ("TTL", 8, 1),
                            ("프로토콜", 9, 1), ("출발지 주소", 12, 4), ("목적지 주소", 16, 4)]))
    print(f"      {ipv4(ip_pkt[12:16])} → {ipv4(ip_pkt[16:20])}, "
          f"다음은 {PROTOCOLS.get(ip_pkt[9], ip_pkt[9])}")
    if args.hex:
        print(hexdump(ip_pkt[:ihl], offset=link_len))
    print(f"      벗기면 남는 것: {len(ip_pkt) - ihl}바이트")
    print()

    # ── 3층 ──────────────────────────────────────────────────────────
    flags = struct.unpack("!H", seg[12:14])[0] & 0xFF
    names = [n for bit, n in FLAG_NAMES if flags & bit]
    print(f"3층. 전송 — TCP, {tcp_hlen}바이트")
    print(annotate(seg, [("출발지 포트", 0, 2), ("목적지 포트", 2, 2),
                         ("순서 번호", 4, 4), ("확인 번호", 8, 4),
                         ("옵셋+플래그", 12, 2), ("윈도 크기", 14, 2)]))
    print(f"      포트 {sport} → {dport}, 플래그 {'+'.join(names) or '-'}")
    if tcp_hlen > 20:
        print(f"      옵션이 {tcp_hlen - 20}바이트 붙어 있다. 그래서 20이 아니라 {tcp_hlen}이다.")
        print("      20으로 고정해 세면 계산이 어긋난다. 데이터 옵셋 필드를 읽어야 한다.")
    if args.hex:
        print(hexdump(seg[:tcp_hlen], offset=link_len + ihl))
    print(f"      벗기면 남는 것: {len(payload)}바이트")
    print()

    # ── 4층 ──────────────────────────────────────────────────────────
    print(f"4층. 애플리케이션 — {app or '알 수 없음'}, {len(payload)}바이트")
    if payload:
        print(f"      {describe_app(app, payload)}")
        if args.hex:
            print(hexdump(payload[:64], offset=link_len + ihl + tcp_hlen))
        else:
            print(f"      앞 60바이트: {payload[:60]!r}")
    else:
        print("      본문이 없다. 핸드셰이크나 ACK처럼 TCP가 스스로 쓰는 세그먼트다.")
    print()

    # ── 셈 ───────────────────────────────────────────────────────────
    overhead = link_len + ihl + tcp_hlen
    print("=" * 74)
    print("이 프레임에서 각 계층이 쓴 바이트")
    print("=" * 74)
    for label, size in [("1층 이더넷", link_len), ("2층 IP", ihl), ("3층 TCP", tcp_hlen),
                        (f"4층 {app or '앱'}", len(payload))]:
        bar = "█" * max(1, round(size / len(data) * 50)) if size else ""
        print(f"  {label:<14} {size:>4}바이트  {bar}")
    print(f"  {'합계':<14} {len(data):>4}바이트")
    print()
    print(f"  헤더가 {overhead}바이트, 애플리케이션이 {len(payload)}바이트다.")
    if len(data):
        print(f"  애플리케이션이 차지하는 비율 {len(payload) / len(data) * 100:.1f}%")
    if payload and app == "MQTT":
        print("  여기서 MQTT 헤더를 또 빼면 실제 센서 값은 몇 바이트 안 된다.")
        print("  overhead.py 가 그것까지 센다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
