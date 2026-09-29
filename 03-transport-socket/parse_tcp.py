#!/usr/bin/env python3
"""캡처에서 TCP 헤더를 읽고 연결이 열리고 닫히는 과정을 짚는다.

TCP 헤더는 옵션이 없으면 20바이트지만 실제로는 그보다 길다. 요즘 운영체제는
타임스탬프 옵션을 기본으로 켜 두어 32바이트로 잡히는 일이 흔하다. 데이터
오프셋 필드가 실제 헤더 길이를 알려 주니 그 값을 읽어 확인해야 한다.

    ┌───────────────────┬───────────────────┐
    │  출발지 포트(16)  │  목적지 포트(16)  │
    ├───────────────────┴───────────────────┤
    │            순서 번호(32)              │
    ├───────────────────────────────────────┤
    │            확인 번호(32)              │
    ├──────┬─────┬────────┬─────────────────┤
    │오프셋(4)│예약 │플래그(8)│  윈도 크기(16) │
    ├──────┴─────┴────────┼─────────────────┤
    │     체크섬(16)      │  긴급 포인터(16)│
    └─────────────────────┴─────────────────┘

플래그 여덟 개 가운데 셋만 봐도 연결의 일생이 읽힌다. SYN은 "연결을 열자",
ACK는 "받았다", FIN은 "내 할 말은 끝났다"이다.

    3-way handshake:  SYN  →  SYN+ACK  →  ACK
    4-way close:      FIN  →  ACK  →  FIN  →  ACK
                      (받는 쪽이 FIN과 ACK를 한 번에 묶으면 3개로 잡힌다)

    sudo tcpdump -i lo0 -c 40 -w samples/tcp.pcap port 9000
    python3 parse_tcp.py samples/tcp.pcap
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.hexdump import ipv4  # noqa: E402
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

FLAG_NAMES = [(0x02, "SYN"), (0x10, "ACK"), (0x01, "FIN"),
              (0x04, "RST"), (0x08, "PSH"), (0x20, "URG")]

OPTION_NAMES = {0: "끝", 1: "채움(NOP)", 2: "최대 세그먼트 크기(MSS)",
                3: "윈도 크기 배수", 4: "선택 확인 허용(SACK)", 5: "선택 확인",
                8: "타임스탬프"}


def parse_options(raw):
    """TCP 옵션을 이름으로 풀어 준다. 헤더가 20바이트를 넘는 이유가 여기 있다."""
    out, i = [], 0
    while i < len(raw):
        kind = raw[i]
        if kind in (0, 1):
            out.append(OPTION_NAMES[kind])
            i += 1
            continue
        if i + 1 >= len(raw):
            break
        length = raw[i + 1]
        if length < 2:
            break
        out.append(f"{OPTION_NAMES.get(kind, kind)}({length}바이트)")
        i += length
    return out


def main():
    ap = argparse.ArgumentParser(description="TCP 헤더와 연결 흐름을 읽는다")
    ap.add_argument("pcap")
    ap.add_argument("-n", "--count", type=int, default=30)
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    shown, saw_syn, saw_fin, header_sizes = 0, 0, 0, set()
    with f:
        print(f"링크 종류: {f.linktype_name}\n")
        print(f"{'번호':<4} {'흐름':<43} {'플래그':<16} {'헤더':<6} 데이터")
        print("-" * 92)
        for ts, data, _ in f:
            _, ip_pkt, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800 or len(ip_pkt) < 20:
                continue
            ihl = (ip_pkt[0] & 0x0F) * 4
            if ip_pkt[9] != 6:            # 프로토콜 6 = TCP
                continue
            total_len = struct.unpack("!H", ip_pkt[2:4])[0]
            seg = ip_pkt[ihl:total_len]
            if len(seg) < 20:
                continue

            sport, dport, seq, ack = struct.unpack("!HHII", seg[:12])
            offset_flags = struct.unpack("!H", seg[12:14])[0]
            tcp_hlen = (offset_flags >> 12) * 4
            flags = offset_flags & 0xFF
            window = struct.unpack("!H", seg[14:16])[0]
            payload_len = total_len - ihl - tcp_hlen

            names = [n for bit, n in FLAG_NAMES if flags & bit]
            saw_syn += ("SYN" in names)
            saw_fin += ("FIN" in names)
            header_sizes.add(tcp_hlen)

            shown += 1
            if shown > args.count:
                break
            flow = f"{ipv4(ip_pkt[12:16])}:{sport} → {ipv4(ip_pkt[16:20])}:{dport}"
            print(f"{shown:<4} {flow:<43} {'+'.join(names) or '-':<16} "
                  f"{tcp_hlen:<6} {payload_len}")

            if shown <= 4 and tcp_hlen > 20:
                opts = parse_options(seg[20:tcp_hlen])
                print(f"     └ 옵션 {tcp_hlen - 20}바이트: {', '.join(opts)}")
            if "SYN" in names and "ACK" not in names:
                print(f"     └ 연결을 열자는 첫 신호다. 순서 번호는 {seq} 에서 시작한다.")
            if "FIN" in names:
                print("     └ 보낼 것을 다 보냈다는 신호다.")

    print()
    print(f"SYN {saw_syn}개, FIN {saw_fin}개를 보았다.")
    print(f"이 캡처에 나온 TCP 헤더 길이: {sorted(header_sizes)}바이트")
    if header_sizes and max(header_sizes) > 20:
        print("20보다 큰 값이 있다. 옵션이 붙어 있다는 뜻이다.")
        print("06 폴더에서 오버헤드를 셀 때 20으로 고정해 세면 계산이 어긋난다.")
    if saw_fin and saw_fin < 2:
        print("FIN이 하나뿐이다. 받는 쪽이 FIN과 ACK를 한 세그먼트로 묶었을 수 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
