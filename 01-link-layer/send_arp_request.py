#!/usr/bin/env python3
"""ARP 요청 프레임을 바이트로 직접 만들어 선에 내보낸다.

앞의 두 스크립트는 남이 만든 프레임을 읽었다. 이번에는 직접 만든다. 이더넷
헤더 14바이트와 ARP 본문 28바이트를 손으로 조립해 42바이트를 그대로 내보낸다.
운영체제의 TCP/IP 스택을 거치지 않고 랜카드에 바로 넣는 셈이다.

AF_PACKET은 리눅스에만 있다. macOS와 BSD는 같은 일을 BPF 장치(/dev/bpf*)로
하는데 다루는 법이 꽤 달라서 여기서는 리눅스만 다룬다. macOS에서는 이 파일을
읽고 프레임이 어떻게 조립되는지만 확인한 뒤, parse_arp.py로 남이 보낸 요청을
읽는 쪽으로 대신한다.

    sudo python3 send_arp_request.py eth0 192.168.0.1
"""

import argparse
import socket
import struct
import sys

ETH_P_ARP = 0x0806


def build_arp_request(src_mac, src_ip, target_ip):
    """이더넷 헤더 14바이트 + ARP 본문 28바이트 = 42바이트를 만든다."""
    # 이더넷 헤더: 아직 상대 MAC을 모르니 목적지는 브로드캐스트로 채운다.
    eth = struct.pack("!6s6sH", b"\xff" * 6, src_mac, ETH_P_ARP)

    # ARP 본문. 찾는 MAC 자리는 전부 0으로 둔다. 그 자리를 채워 달라는 뜻이다.
    arp = struct.pack(
        "!HHBBH6s4s6s4s",
        1,               # 하드웨어 종류: 1 = 이더넷
        0x0800,          # 프로토콜 종류: IPv4
        6,               # MAC 주소 길이
        4,               # IP 주소 길이
        1,               # 연산: 1 = 요청
        src_mac,
        socket.inet_aton(src_ip),
        b"\x00" * 6,
        socket.inet_aton(target_ip),
    )
    return eth + arp


def main():
    ap = argparse.ArgumentParser(description="ARP 요청을 직접 만들어 보낸다 (리눅스 전용)")
    ap.add_argument("interface", help="내보낼 인터페이스 이름 (예: eth0)")
    ap.add_argument("target_ip", help="MAC 주소를 묻고 싶은 IP")
    ap.add_argument("--timeout", type=float, default=2.0, help="응답을 기다릴 초 (기본 2)")
    args = ap.parse_args()

    if not hasattr(socket, "AF_PACKET"):
        print("AF_PACKET이 없다. 이 스크립트는 리눅스에서만 돈다.", file=sys.stderr)
        print("macOS에서는 parse_arp.py로 캡처한 ARP를 읽는 쪽으로 대신한다.", file=sys.stderr)
        return 2

    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP))
    except PermissionError:
        print("권한이 없다. sudo를 붙여 다시 돌린다.", file=sys.stderr)
        return 1
    sock.bind((args.interface, 0))
    src_mac = sock.getsockname()[4]

    # 내 IP는 아무 주소로나 UDP 소켓을 열어 커널이 고른 출발지 주소를 본다.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect((args.target_ip, 9))
    src_ip = probe.getsockname()[0]
    probe.close()

    frame = build_arp_request(src_mac, src_ip, args.target_ip)
    print(f"만든 프레임 {len(frame)}바이트 (이더넷 14 + ARP 28)")
    print("  " + " ".join(f"{b:02x}" for b in frame))
    sock.send(frame)
    print(f"{args.interface}로 내보냈다. {args.target_ip}의 MAC을 묻는 중이다.")

    sock.settimeout(args.timeout)
    try:
        while True:
            data = sock.recv(2048)
            op = struct.unpack("!H", data[20:22])[0]
            sender_ip = socket.inet_ntoa(data[28:32])
            if op == 2 and sender_ip == args.target_ip:
                sender_mac = ":".join(f"{b:02x}" for b in data[22:28])
                print(f"답이 왔다. {args.target_ip} 의 MAC은 {sender_mac} 이다.")
                return 0
    except socket.timeout:
        print(f"{args.timeout}초 안에 답이 없다. 그 IP를 쓰는 기기가 랜에 없을 수 있다.")
        return 1
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
