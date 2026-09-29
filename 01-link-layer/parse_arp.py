#!/usr/bin/env python3
"""캡처에서 ARP 요청과 응답을 뽑아 읽는다.

ARP는 "이 IP 주소를 쓰는 사람, MAC 주소가 뭔가"를 같은 랜에 대고 묻는 규약이다.
IP 주소를 다루지만 IP 위에서 라우팅되지 않는다. 그래서 인터넷 계층이 아니라
이 계층에 속한다. 이더타입 0x0806으로 이더넷 헤더 바로 뒤에 붙는다.

    ┌────────┬────────┬──────┬──────┬────────┬────────┬───────┬────────┬───────┐
    │ 하드웨어│프로토콜│ HLEN │ PLEN │ 연산   │보낸 MAC│보낸 IP│찾는 MAC│찾는 IP│
    │  2     │   2    │  1   │  1   │  2     │   6    │   4   │   6    │   4   │
    └────────┴────────┴──────┴──────┴────────┴────────┴───────┴────────┴───────┘

연산이 1이면 요청, 2면 응답이다. 요청에서는 '찾는 MAC'이 전부 0이다. 아직
모르니까 비워 두고 묻는 것이다. 응답이 그 자리를 채워서 돌아온다.

    sudo arp -d -a                 # macOS. 리눅스는 sudo ip neigh flush all
    sudo tcpdump -i en0 -w samples/arp.pcap arp &
    ping -c 1 192.168.0.1
    python3 parse_arp.py samples/arp.pcap
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.hexdump import ipv4, mac  # noqa: E402
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

OPCODES = {1: "요청(누가 이 IP를 쓰나)", 2: "응답(내가 쓴다)"}


def parse_arp(payload):
    if len(payload) < 28:
        return None
    htype, ptype, hlen, plen, op = struct.unpack("!HHBBH", payload[:8])
    if htype != 1 or ptype != 0x0800 or hlen != 6 or plen != 4:
        return None  # 이더넷 + IPv4 조합만 다룬다
    return {
        "op": op,
        "sender_mac": payload[8:14],
        "sender_ip": payload[14:18],
        "target_mac": payload[18:24],
        "target_ip": payload[24:28],
    }


def main():
    ap = argparse.ArgumentParser(description="ARP 요청과 응답을 읽는다")
    ap.add_argument("pcap")
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    pending = {}  # 요청을 기록해 두었다가 응답이 오면 짝을 맞춘다
    found = 0
    with f:
        for ts, data, _ in f:
            _, payload, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0806:
                continue
            arp = parse_arp(payload)
            if not arp:
                continue
            found += 1
            sip, tip = ipv4(arp["sender_ip"]), ipv4(arp["target_ip"])
            print(f"[{ts:.6f}] {OPCODES.get(arp['op'], arp['op'])}")
            print(f"    보낸 쪽 {mac(arp['sender_mac'])} / {sip}")
            print(f"    찾는 쪽 {mac(arp['target_mac'])} / {tip}")
            if arp["op"] == 1:
                pending[tip] = ts
                if arp["target_mac"] == bytes(6):
                    print("    찾는 MAC이 전부 0이다. 아직 모르니 비워 두고 묻는 것이다.")
                else:
                    print("    찾는 MAC이 채워져 있다. 확인용 요청(gratuitous ARP)일 수 있다.")
            elif arp["op"] == 2 and sip in pending:
                print(f"    {(ts - pending.pop(sip)) * 1000:.2f}ms 만에 답이 왔다.")
            print()

    if found == 0:
        print("ARP 패킷이 없다. 캐시를 비우고 같은 랜의 기기에 ping을 보낸 뒤 다시 잡는다.")
    else:
        print(f"ARP 패킷 {found}개를 읽었다.")
        if pending:
            print(f"답이 오지 않은 요청: {', '.join(pending)}")
            print("그 주소를 쓰는 기기가 랜에 없거나 응답하지 않는다는 뜻이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
