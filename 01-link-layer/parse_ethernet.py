#!/usr/bin/env python3
"""캡처한 프레임의 이더넷 헤더를 바이트 단위로 갈라 읽는다.

이더넷 헤더는 14바이트로 고정이다.

    ┌──────────────┬──────────────┬───────────┐
    │ 목적지 MAC   │ 출발지 MAC   │ 이더타입  │
    │   6바이트    │   6바이트    │  2바이트  │
    └──────────────┴──────────────┴───────────┘

이더타입이 그다음 계층을 알려 준다. 0x0800이면 IPv4, 0x0806이면 ARP,
0x86DD면 IPv6다. 즉 1층 헤더의 마지막 2바이트가 2층으로 넘기는 이정표다.
계층이 위아래로 이어지는 방식이 이렇게 생겼다.

    sudo tcpdump -i en0 -c 20 -w samples/eth.pcap
    python3 parse_ethernet.py samples/eth.pcap
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.hexdump import annotate, hexdump, mac  # noqa: E402
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

ETHERTYPES = {
    0x0800: "IPv4",
    0x0806: "ARP",
    0x86DD: "IPv6",
    0x8100: "VLAN(802.1Q)",
    0x88CC: "LLDP",
}


def main():
    ap = argparse.ArgumentParser(description="이더넷 헤더를 갈라 읽는다")
    ap.add_argument("pcap", help="tcpdump -w 로 저장한 pcap 파일")
    ap.add_argument("-n", "--count", type=int, default=5, help="몇 개까지 볼지 (기본 5)")
    ap.add_argument("-x", "--hex", action="store_true", help="16진수 덤프도 함께 찍는다")
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    with f:
        print(f"파일       : {args.pcap}")
        print(f"링크 종류  : {f.linktype_name} (헤더 {f.link_header_len}바이트)")
        if f.linktype_name != "EN10MB":
            print()
            print("이 캡처에는 이더넷 헤더가 없다.")
            print("루프백(lo0)이나 -i any로 잡으면 이렇게 나온다.")
            print("물리 인터페이스(en0, eth0)를 잡아야 이더넷 헤더가 보인다.")
            return 0
        print()

        shown = 0
        for ts, data, orig_len in f:
            if shown >= args.count:
                break
            shown += 1
            dst, src = data[0:6], data[6:12]
            ethertype = int.from_bytes(data[12:14], "big")
            name = ETHERTYPES.get(ethertype, f"0x{ethertype:04x}")

            print(f"[{shown}] {ts:.6f}  잡은 길이 {len(data)}바이트 / 원래 길이 {orig_len}바이트")
            print(annotate(data, [("목적지 MAC", 0, 6), ("출발지 MAC", 6, 6), ("이더타입", 12, 2)]))
            print(f"      목적지 {mac(dst)}  →  출발지 {mac(src)}   다음 계층: {name}")
            if dst == b"\xff" * 6:
                print("      목적지가 전부 ff다. 같은 랜의 모두에게 뿌리는 브로드캐스트다.")
            if src[0] & 0x02:
                print("      출발지 첫 바이트의 둘째 비트가 서 있다. 소프트웨어가 붙인 주소다.")
            if args.hex:
                print(hexdump(data[:14]))
            print(f"      그 위 계층으로 넘어가는 바이트: {len(data) - 14}바이트")
            print()

        if shown == 0:
            print("패킷이 하나도 없다. 캡처를 다시 떠 본다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
