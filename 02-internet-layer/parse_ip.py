#!/usr/bin/env python3
"""캡처에서 IP 헤더를 필드별로 갈라 읽는다.

IPv4 헤더는 옵션이 없으면 20바이트다.

     0               1               2               3
     0 1 2 3 4 5 6 7 8 ...                                 31
    ┌───────┬───────┬───────────────┬───────────────────────┐
    │버전(4)│IHL(4) │    TOS(8)     │      전체 길이(16)    │
    ├───────┴───────┴───────────────┼───┬───────────────────┤
    │        식별자(16)             │FLG│  단편 오프셋(13)    │
    ├───────────────┬───────────────┼───┴───────────────────┤
    │   TTL(8)      │  프로토콜(8)  │    헤더 체크섬(16)    │
    ├───────────────┴───────────────┴───────────────────────┤
    │                   출발지 주소(32)                     │
    ├───────────────────────────────────────────────────────┤
    │                   목적지 주소(32)                     │
    └───────────────────────────────────────────────────────┘

눈여겨볼 곳이 셋이다. IHL은 4바이트 단위라 보통 5(=20바이트)다. TTL은 라우터를
지날 때마다 1씩 줄고 0이 되면 버려진다. traceroute가 이 성질을 이용한다.
프로토콜 필드가 그 위 계층을 알려 준다. 6이면 TCP, 17이면 UDP, 1이면 ICMP다.
1층의 이더타입과 같은 구실을 2층에서 하는 셈이다.

    python3 parse_ip.py ../01-link-layer/samples/en0-all.pcap
"""

import argparse
import pathlib
import socket
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.hexdump import annotate, ipv4  # noqa: E402
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

PROTOCOLS = {1: "ICMP", 6: "TCP", 17: "UDP", 2: "IGMP", 89: "OSPF"}


def parse_ipv4(pkt):
    if len(pkt) < 20:
        return None
    ver_ihl = pkt[0]
    version, ihl = ver_ihl >> 4, (ver_ihl & 0x0F) * 4
    if version != 4 or len(pkt) < ihl:
        return None
    total_len, ident, flags_frag, ttl, proto, csum = struct.unpack("!HHHBBH", pkt[2:12])
    return {
        "ihl": ihl,
        "total_len": total_len,
        "ident": ident,
        "df": bool(flags_frag & 0x4000),
        "mf": bool(flags_frag & 0x2000),
        "frag_offset": (flags_frag & 0x1FFF) * 8,
        "ttl": ttl,
        "proto": proto,
        "checksum": csum,
        "src": pkt[12:16],
        "dst": pkt[16:20],
        "payload": pkt[ihl:total_len] if total_len >= ihl else pkt[ihl:],
    }


def main():
    ap = argparse.ArgumentParser(description="IP 헤더를 갈라 읽는다")
    ap.add_argument("pcap")
    ap.add_argument("-n", "--count", type=int, default=5)
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    shown = 0
    with f:
        print(f"링크 종류: {f.linktype_name}\n")
        for ts, data, _ in f:
            link_len, payload, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800:
                continue
            ip = parse_ipv4(payload)
            if not ip:
                continue
            shown += 1
            if shown > args.count:
                break

            print(f"[{shown}] {ts:.6f}")
            print(annotate(payload, [
                ("버전+IHL", 0, 1), ("TOS", 1, 1), ("전체 길이", 2, 2),
                ("식별자", 4, 2), ("플래그+단편오프셋", 6, 2),
                ("TTL", 8, 1), ("프로토콜", 9, 1), ("헤더 체크섬", 10, 2),
                ("출발지 주소", 12, 4), ("목적지 주소", 16, 4),
            ]))
            proto = PROTOCOLS.get(ip["proto"], str(ip["proto"]))
            print(f"      {ipv4(ip['src'])} → {ipv4(ip['dst'])}   위 계층: {proto}   TTL {ip['ttl']}")
            print(f"      헤더 {ip['ihl']}바이트 + 데이터 {ip['total_len'] - ip['ihl']}바이트 "
                  f"= 전체 {ip['total_len']}바이트")
            if ip["df"]:
                print("      DF 비트가 서 있다. 라우터가 이 패킷을 쪼개지 못한다.")
            if ip["mf"] or ip["frag_offset"]:
                print(f"      쪼개진 조각이다. 오프셋 {ip['frag_offset']}바이트")
            print(f"      링크 헤더 {link_len} + IP 헤더 {ip['ihl']} = "
                  f"여기까지 덧씌운 바이트 {link_len + ip['ihl']}")
            print()

    if shown == 0:
        print("IPv4 패킷이 없다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
