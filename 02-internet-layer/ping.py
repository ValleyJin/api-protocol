#!/usr/bin/env python3
"""ICMP Echo 요청을 직접 만들어 보내는 ping.

운영체제의 ping 명령을 쓰지 않고 ICMP 패킷을 바이트로 조립한다. IP 헤더는
커널이 붙여 주고, 그 위의 ICMP 메시지만 직접 만든다. 이것이 "2층을 직접
다룬다"는 말의 실제 모습이다.

ICMP Echo 메시지는 8바이트 헤더에 아무 데이터나 붙인 것이다.

    ┌────────┬────────┬────────────┬────────────┬────────────┐
    │ 타입(1)│ 코드(1)│ 체크섬(2)  │ 식별자(2)  │ 순번(2)    │  + 데이터
    └────────┴────────┴────────────┴────────────┴────────────┘

타입 8이 요청, 0이 응답이다. 받는 쪽은 데이터를 그대로 되돌려 보낸다.
왕복 시간을 재려고 데이터 앞머리에 보낸 시각을 적어 넣는다.

소켓을 여는 방법이 둘이다. SOCK_RAW는 관리자 권한이 필요하고, SOCK_DGRAM +
IPPROTO_ICMP는 macOS에서 권한 없이 열린다. 리눅스는 net.ipv4.ping_group_range
설정에 따라 갈린다. 아래 코드는 권한 없는 쪽을 먼저 해 보고 안 되면 넘어간다.

    python3 ping.py 8.8.8.8
    python3 ping.py example.com -c 5
"""

import argparse
import os
import socket
import struct
import sys
import time

from checksum import internet_checksum

ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0


def build_echo(ident, seq, payload_size=32):
    """ICMP Echo 요청 한 개를 바이트로 만든다."""
    # 데이터 앞 8바이트에 보낸 시각을 넣어 두면 응답에 그대로 실려 돌아온다.
    now = struct.pack("!d", time.time())
    payload = now + bytes((i & 0xFF) for i in range(payload_size - len(now)))

    # 체크섬을 구하려면 체크섬 자리를 0으로 둔 채 한 번 만들어야 한다.
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, 0, ident, seq)
    csum = internet_checksum(header + payload)
    header = struct.pack("!BBHHH", ICMP_ECHO_REQUEST, 0, csum, ident, seq)
    return header + payload


def open_socket():
    """권한 없는 소켓을 먼저 해 보고, 안 되면 raw 소켓으로 넘어간다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
        return s, "SOCK_DGRAM (권한 없이 열렸다)"
    except PermissionError:
        pass
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        return s, "SOCK_RAW (관리자 권한)"
    except PermissionError:
        print("소켓을 열지 못했다. sudo를 붙이거나, 리눅스라면 아래를 확인한다.", file=sys.stderr)
        print("  sysctl net.ipv4.ping_group_range   # 내 그룹이 범위 안에 있어야 한다", file=sys.stderr)
        raise SystemExit(1)


def strip_ip_header(data):
    """raw 소켓으로 받으면 IP 헤더가 붙어 온다. DGRAM 소켓은 안 붙는다."""
    if len(data) >= 20 and (data[0] >> 4) == 4:
        ihl = (data[0] & 0x0F) * 4
        if len(data) > ihl and data[ihl] in (ICMP_ECHO_REPLY, 11, 3):
            return data[ihl:], data[8]  # (ICMP 부분, TTL)
    return data, None


def main():
    ap = argparse.ArgumentParser(description="ICMP Echo를 직접 만들어 보낸다")
    ap.add_argument("host")
    ap.add_argument("-c", "--count", type=int, default=4, help="보낼 횟수 (기본 4)")
    ap.add_argument("-s", "--size", type=int, default=32, help="데이터 바이트 수 (기본 32)")
    ap.add_argument("-W", "--timeout", type=float, default=2.0)
    args = ap.parse_args()

    try:
        dest = socket.gethostbyname(args.host)
    except socket.gaierror as exc:
        print(f"이름을 풀지 못했다: {exc}", file=sys.stderr)
        return 1

    sock, how = open_socket()
    sock.settimeout(args.timeout)
    ident = os.getpid() & 0xFFFF

    print(f"PING {args.host} ({dest}) 데이터 {args.size}바이트 — 소켓: {how}")
    rtts = []
    for seq in range(1, args.count + 1):
        packet = build_echo(ident, seq, args.size)
        sent_at = time.time()
        sock.sendto(packet, (dest, 0))
        try:
            while True:
                data, addr = sock.recvfrom(2048)
                icmp, ttl = strip_ip_header(data)
                if len(icmp) < 8:
                    continue
                icmp_type, _, _, _, got_seq = struct.unpack("!BBHHH", icmp[:8])
                # SOCK_DGRAM으로 열면 커널이 식별자를 제 것으로 바꿔 버린다.
                # 그래서 식별자 대신 순번으로 짝을 맞춘다.
                if icmp_type == ICMP_ECHO_REPLY and got_seq == seq:
                    rtt = (time.time() - sent_at) * 1000
                    rtts.append(rtt)
                    ttl_text = f" ttl={ttl}" if ttl is not None else ""
                    print(f"{len(icmp)}바이트 ← {addr[0]}: seq={seq}{ttl_text} 시간={rtt:.2f}ms")
                    break
                if icmp_type == 11:
                    print(f"seq={seq}: TTL 초과 — {addr[0]} 에서 버려졌다")
                    break
        except socket.timeout:
            print(f"seq={seq}: {args.timeout}초 안에 답이 없다")
        if seq < args.count:
            time.sleep(0.5)

    sock.close()
    print(f"\n--- {args.host} 통계 ---")
    lost = args.count - len(rtts)
    print(f"보낸 {args.count}개, 받은 {len(rtts)}개, 잃은 비율 {lost / args.count * 100:.0f}%")
    if rtts:
        print(f"최소 {min(rtts):.2f}ms / 평균 {sum(rtts) / len(rtts):.2f}ms / 최대 {max(rtts):.2f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
