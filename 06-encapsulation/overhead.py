#!/usr/bin/env python3
"""캡처 전체를 훑어 계층별 오버헤드를 세고 프로토콜끼리 견준다.

peel.py 가 한 프레임을 벗겼다면 여기서는 흐름 전체를 센다. 값 하나를 나르는
데 실제로 얼마가 드는지, 프로토콜을 바꾸면 얼마나 달라지는지 숫자로 나온다.

    python3 ../tools/make_sample_pcap.py samples/sample.pcap
    python3 overhead.py samples/sample.pcap
"""

import argparse
import pathlib
import struct
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "04-application" / "mqtt"))
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

KNOWN_PORTS = {80: "HTTP", 8080: "HTTP", 8000: "HTTP", 9200: "HTTP",
               1883: "MQTT", 5683: "CoAP", 53: "DNS", 8081: "WebSocket", 9500: "WebSocket"}


def app_name(sport, dport):
    for port in (sport, dport):
        if port in KNOWN_PORTS:
            return KNOWN_PORTS[port]
    return f"포트 {min(sport, dport)}"


def mqtt_value_bytes(stream):
    """MQTT 스트림에서 실제 센서 값이 몇 바이트인지 센다."""
    import mqtt
    total, packets = 0, 0
    buffer = stream
    while True:
        msg, buffer = mqtt.decode(buffer)
        if msg is None:
            return total, packets
        packets += 1
        if msg["type"] == mqtt.PUBLISH:
            total += len(msg["payload"])


def http_body_bytes(stream):
    """HTTP 스트림에서 본문이 몇 바이트인지 센다."""
    total, messages = 0, 0
    pos = 0
    while True:
        sep = stream.find(b"\r\n\r\n", pos)
        if sep < 0:
            return total, messages
        head = stream[pos:sep].decode("latin-1", "replace")
        messages += 1
        length = 0
        for line in head.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = 0
        total += length
        pos = sep + 4 + length


def main():
    ap = argparse.ArgumentParser(description="계층별 오버헤드를 센다")
    ap.add_argument("pcap")
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    # 방향마다 스트림을 따로 모은다. 요청과 응답을 한 바구니에 담으면 파싱이 깨진다.
    flows = defaultdict(lambda: {"frames": 0, "link": 0, "ip": 0, "tcp": 0, "app": 0,
                                 "c2s": b"", "s2c": b"", "total": 0})
    # 프레임마다 머리글 합을 따로 재어 둔다. 1층과 2층이 늘 14, 20인 캡처만 보면
    # 54~70 같은 닫힌 범위를 외우게 된다. VLAN 태그나 IP 옵션이 붙은 캡처에서는
    # 그 범위가 깨지므로 범위를 박아 두지 않고 지금 센 값에서 구해 찍는다.
    header_lens = []
    # 잡힌 길이가 원래 길이보다 짧은 프레임을 센다. 머리글은 멀쩡히 읽히니
    # 건너뛰지 않는데, 4층과 합계가 잡힌 만큼만 나와 비율이 조용히 작아진다.
    truncated = 0
    layer_seen = {"link": set(), "ip": set(), "tcp": set()}
    # 센 프레임만 적고 버린 것을 말하지 않으면 "프레임마다"가 무엇을 가리키는지
    # 알 수 없다. 진짜 캡처는 거의 다 섞여 있다.
    skipped = 0

    with f:
        print(f"파일      : {args.pcap}")
        print(f"링크 종류 : {f.linktype_name}")
        if f.linktype_name != "EN10MB":
            print()
            print("⚠ 이더넷이 아니다. 루프백이나 -i any 로 잡으면 이렇게 된다.")
            print("  실제 링크에서 오가는 프레임이 아니라 1층 오버헤드가 어긋난다.")
            print("  브로커를 다른 기기나 VM에 띄우고 물리 인터페이스에서 다시 잡는다.")
        print()

        for ts, data, orig_len in f:
            link_len, ip_pkt, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800 or len(ip_pkt) < 20 or ip_pkt[9] != 6:
                skipped += 1          # IPv4 위의 TCP가 아니다
                continue
            ihl = (ip_pkt[0] & 0x0F) * 4
            total_len = struct.unpack("!H", ip_pkt[2:4])[0]
            frag_off = struct.unpack("!H", ip_pkt[6:8])[0] & 0x1FFF
            if ihl < 20 or total_len < ihl or frag_off:
                # IHL 이 20 미만이면 머리글을 읽을 수 없고, total_len 이 머리글보다
                # 짧으면 길이 필드가 망가진 것이다. 조각난 프레임은 첫 조각만
                # TCP 머리글을 들고 있으니 뒤 조각을 세면 엉뚱한 숫자가 나온다.
                # 세 경우를 말없이 세면 표가 조용히 틀린다.
                skipped += 1
                continue
            seg = ip_pkt[ihl:total_len]
            if len(seg) < 20:
                skipped += 1
                continue
            sport, dport = struct.unpack("!HH", seg[:4])
            tcp_hlen = (struct.unpack("!H", seg[12:14])[0] >> 12) * 4
            if tcp_hlen < 20 or tcp_hlen > len(seg):
                # 데이터 오프셋이 5 미만이거나 세그먼트보다 크면 읽을 수 없다.
                skipped += 1
                continue
            payload = seg[tcp_hlen:]

            key = app_name(sport, dport)
            flow = flows[key]
            flow["frames"] += 1
            flow["link"] += link_len
            flow["ip"] += ihl
            flow["tcp"] += tcp_hlen
            flow["app"] += len(payload)
            flow["total"] += len(data)
            if len(data) < orig_len:
                truncated += 1
            header_lens.append(link_len + ihl + tcp_hlen)
            layer_seen["link"].add(link_len)
            layer_seen["ip"].add(ihl)
            layer_seen["tcp"].add(tcp_hlen)
            if dport in KNOWN_PORTS:
                flow["c2s"] += payload      # 클라이언트 → 서버 (요청)
            else:
                flow["s2c"] += payload      # 서버 → 클라이언트 (응답)

    if not flows:
        # 여기서 돌아 나가면 아래 정리 절을 못 찍는다. MPLS나 PPPoE 캡처처럼
        # 전부 버려지는 경우가 그 설명이 가장 필요한 때다.
        if skipped:
            print(f"  이 캡처의 {skipped}프레임은 모두 IPv4 위의 TCP로 읽히지 않아 세지 않았다.")
            print("  이 셈은 IPv4 위의 TCP만 센다. 이더타입을 읽지 못했거나 IPv4가 아니거나(IPv6, ARP,")
            print("  MPLS, PPPoE), IP의 프로토콜 번호가 6이 아니거나(UDP, ICMP), 조각난")
            print("  프레임의 뒤 조각이거나, IP와 TCP 머리글을 끝까지 읽을 수 없는 프레임은")
            print("  건너뛴다. 머리글을 못 읽는 경우는 스냅 길이를 머리글보다 짧게 걸고 잡은")
            print("  캡처와, IP 전체 길이나 IHL, TCP 데이터 오프셋이 머리글보다 짧게 적힌")
            print("  캡처다.")
        else:
            # 프레임이 한 장도 없으면 버린 것도 없다. 그 말을 안 하면 읽는
            # 사람이 자기 필터를 의심한다.
            print("  이 캡처에는 프레임이 한 장도 없다.")
        print("TCP 흐름을 찾지 못했다.")
        return 0

    print("=" * 86)
    print(f"{'프로토콜':<12}{'프레임':>7}{'1층':>8}{'2층 IP':>9}{'3층 TCP':>10}"
          f"{'4층 앱':>9}{'합계':>9}{'앱 비율':>9}")
    print("=" * 86)
    for name, flow in flows.items():
        ratio = flow["app"] / flow["total"] * 100 if flow["total"] else 0
        print(f"{name:<12}{flow['frames']:>7}{flow['link']:>8}{flow['ip']:>9}"
              f"{flow['tcp']:>10}{flow['app']:>9}{flow['total']:>9}{ratio:>8.1f}%")
    print("=" * 86)
    print()

    print("여기서 한 겹 더 벗긴다. 4층 바이트에도 프로토콜 자신의 헤더가 들어 있다.")
    print()
    results = {}
    for name, flow in flows.items():
        if name == "MQTT":
            # PUBLISH는 양쪽 다 오간다. 두 방향을 따로 세어 더한다.
            up, n1 = mqtt_value_bytes(flow["c2s"])
            down, n2 = mqtt_value_bytes(flow["s2c"])
            value, label = up + down, f"MQTT 패킷 {n1 + n2}개 중 PUBLISH 값"
        elif name == "HTTP":
            # 본문은 대개 응답에 실린다. 요청 본문(PUT, POST)도 함께 센다.
            up, n1 = http_body_bytes(flow["c2s"])
            down, n2 = http_body_bytes(flow["s2c"])
            value, label = up + down, f"HTTP 메시지 {n1 + n2}개의 본문"
        else:
            continue
        results[name] = (value, flow["total"])
        useful = value / flow["total"] * 100 if flow["total"] else 0
        print(f"  {name:<6} 전체 {flow['total']:>5}바이트 중 실제 값 {value:>4}바이트  "
              f"→ {useful:.1f}%    ({label})")

    if len(results) >= 2 and "MQTT" in results and "HTTP" in results:
        mqtt_value, mqtt_total = results["MQTT"]
        http_value, http_total = results["HTTP"]
        print()
        print("=" * 66)
        print("같은 값을 나르는 데 든 바이트")
        print("=" * 66)
        if mqtt_value and http_value:
            print(f"  HTTP: 값 1바이트를 나르는 데 {http_total / http_value:.1f}바이트를 썼다")
            print(f"  MQTT: 값 1바이트를 나르는 데 {mqtt_total / mqtt_value:.1f}바이트를 썼다")
        print()
        print("  이 숫자를 곧이곧대로 읽으면 안 된다. 두 가지가 비교를 비튼다.")
        print()
        print("  첫째, 실은 다른 것을 나르고 있다. HTTP는 센서 이름과 단위까지 담은 JSON을")
        print("  보냈고 MQTT는 숫자만 보냈다. 값 1바이트당 비용은 많이 담을수록 낮아지니,")
        print("  말이 많은 쪽이 오히려 좋아 보인다. 이 잣대 하나로 우열을 가릴 수 없다.")
        print()
        print("  둘째, 건수가 적다. HTTP는 연결을 맺고 끊는 데 다섯 프레임을 썼고 값은")
        print("  한 번 날랐다. MQTT는 연결 하나로 세 번 날랐다. 건수를 늘리면 MQTT는")
        print("  PUBLISH 프레임만 늘고 HTTP는 핸드셰이크까지 되풀이한다.")
        print()
        print("  제대로 견주려면 같은 것을 같은 횟수만큼 날라야 한다. 04-application 의")
        print("  common/sensor.py 가 그래서 있다. 캡처를 직접 떠서 건수를 바꿔 가며")
        print("  다시 세어 보면 어디서 순서가 뒤집히는지 보인다.")

    def span_of(vals):
        vals = sorted(vals)
        return str(vals[0]) if vals[0] == vals[-1] else f"{vals[0]}~{vals[-1]}"

    def span(key):
        return span_of(layer_seen[key])

    print()
    print("정리")
    if skipped:
        counted = sum(flow["frames"] for flow in flows.values())
        print(f"  이 캡처의 {counted + skipped}프레임 가운데 {skipped}프레임은 IPv4 위의")
        print("  TCP로 읽히지 않아 세지 않았다. 아래 숫자는 나머지를 센 것이다.")
    # 층별 범위를 + 로 잇고 = 로 합을 적으면 거짓이 된다. 세 층의 최솟값이 한
    # 프레임에 함께 나타나지 않으면 양쪽이 안 맞는다. 그래서 합계도 프레임마다
    # 센 값으로 따로 찍는다.
    if truncated:
        print(f"  이 캡처의 {truncated}프레임은 잡힌 길이가 원래 길이보다 짧다.")
        print("  스냅 길이를 걸고 잡은 것이니 4층과 합계가 그만큼 작게 나온다.")
        print("  **앱 비율은 믿을 수 없다.** 머리글은 안 잘리고 4층만 잘리니 분자만 줄고")
        print("  분모는 머리글만큼 남는다. samples/sample.pcap 을 잘라 가며 돌리면 이렇게 된다.")
        print("    스냅 없음  HTTP 40.9%  MQTT 20.4%")
        print("    200바이트  HTTP 35.8%  MQTT 20.4%")
        print("     80바이트  HTTP  5.6%  MQTT 10.1%")
        print("     66바이트  HTTP  0.0%  MQTT  0.0%")
        print("  **스냅 67부터 126까지는 순서가 뒤집힌다.** 안 자르면 40.9%와 20.4%로 HTTP가")
        print("  높은데 80으로 자르면 5.6%와 10.1%로 MQTT가 높다. 127부터 다시 HTTP가")
        print("  높아진다(20.6%와 20.4%). 뒤집힌 구간에서 MQTT가 더 알차서가 아니다.")
        print("  이 캡처에서 MQTT 프레임은 길어도 102바이트라 80으로 자를 때 한 프레임이")
        print("  22바이트씩만 잃는데, HTTP의 263바이트와 194바이트짜리는 183과 114바이트를")
        print("  잃는다. 200바이트에서 MQTT의 20.4%가 그대로인 것도 같은 까닭이다.")
        print("  MQTT 프레임이 다 200 아래라 하나도 잘리지 않는다.")
        print("  비율을 보려면 스냅을 걸지 않는다.")
    print(f"  이 캡처에서는 1층이 {span('link')}, 2층이 {span('ip')}, 3층이 {span('tcp')}바이트였다.")
    print(f"  프레임마다 붙은 머리글은 {span_of(header_lens)}바이트다. 층별 범위를 더한 값이")
    print("  아니라 프레임마다 센 값이다. 가장 작은 값끼리, 가장 큰 값끼리 한 프레임에")
    print("  함께 나타날 때만 양쪽 끝이 맞는다. 그리고 범위는 양 끝만 적은 것이라 그 사이")
    print("  값이 다 나왔다는 뜻이 아니다.")
    print("  이 범위는 이 캡처에서 나온 것이다. VLAN 태그가 붙으면 1층이 18, 태그가 두 개면")
    print("  22가 된다. IP 옵션이 붙으면 2층이 60까지, TCP 옵션은 상한이 40이라 3층이")
    print("  60까지 간다. 세 층이 겹치면 머리글만 140을 넘는다. 다만 이 셈은 IPv4 위의")
    print("  TCP만 센다. UDP나 ICMP, IPv6, ARP, MPLS, PPPoE로 감싼 프레임은 건너뛰고,")
    print("  조각난 프레임의 뒤 조각과, IP와 TCP 머리글을 끝까지 읽을 수 없는 프레임도")
    print("  건너뛴다.")
    print("  캡처를 바꿔 가며 이 줄의 숫자가 어떻게 달라지는지 보는 것이")
    print("  범위를 외우는 것보다 낫다.")
    print("  센서 값 4바이트를 보내려고 그 열 배가 넘는 바이트가 움직인다.")
    print("  좁은 망에서 프로토콜을 고르는 일이 왜 중요한지 이 숫자가 말해 준다.")
    print("  05-api-layers 의 여덟 방식도 결국 이 숫자 위에 얹힌다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
