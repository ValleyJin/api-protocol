#!/usr/bin/env python3
"""TTL을 1부터 올려 가며 중간 라우터를 하나씩 드러낸다.

IP 헤더의 TTL은 라우터를 지날 때마다 1씩 줄고 0이 되면 그 라우터가 패킷을
버린다. 버릴 때 그냥 버리지 않고 "TTL이 다 됐다"는 ICMP 메시지(타입 11)를
보낸 쪽에 돌려준다. 그 메시지의 출발지 주소가 바로 그 라우터다.

그러니 TTL 1로 보내면 첫 라우터가, 2로 보내면 둘째 라우터가 답을 한다.
이렇게 한 홉씩 늘려 가며 경로를 드러내는 것이 traceroute다.

여기서 중요한 사실이 하나 드러난다. 보내는 쪽은 경로를 미리 고르지 않는다.
라우터마다 다음에 넘길 곳을 그때그때 정한다. 그래서 같은 목적지에 여러 번
돌리면 경로가 달라지기도 한다.

    python3 traceroute.py 8.8.8.8
    python3 traceroute.py example.com -m 15 -q 1
"""

import argparse
import os
import socket
import struct
import sys
import time

from checksum import internet_checksum
from ping import build_echo, open_socket, strip_ip_header

ICMP_ECHO_REPLY = 0
ICMP_DEST_UNREACH = 3
ICMP_TIME_EXCEEDED = 11


def resolve_name(ip):
    """주소에 이름이 붙어 있으면 함께 보여 준다. 없으면 주소만 돌려준다."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return None


def probe(sock, dest, ttl, seq, ident, timeout):
    """TTL을 걸고 한 번 찔러 본다. (응답 주소, 왕복 시간, 끝인가) 를 돌려준다."""
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
    sent_at = time.time()
    sock.sendto(build_echo(ident, seq, 32), (dest, 0))

    deadline = sent_at + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return None, None, False
        sock.settimeout(remaining)
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            return None, None, False

        icmp, _ = strip_ip_header(data)
        if len(icmp) < 8:
            continue
        icmp_type = icmp[0]
        rtt = (time.time() - sent_at) * 1000

        if icmp_type == ICMP_TIME_EXCEEDED:
            # 중간 라우터가 버렸다. 그 라우터 주소가 addr다.
            return addr[0], rtt, False
        if icmp_type == ICMP_ECHO_REPLY:
            # 목적지가 직접 답했다. 여기가 끝이다.
            return addr[0], rtt, True
        if icmp_type == ICMP_DEST_UNREACH:
            return addr[0], rtt, True


def main():
    ap = argparse.ArgumentParser(description="TTL을 올려 가며 경로를 드러낸다")
    ap.add_argument("host")
    ap.add_argument("-m", "--max-hops", type=int, default=20, help="최대 홉 수 (기본 20)")
    ap.add_argument("-q", "--queries", type=int, default=3, help="홉마다 찔러 볼 횟수 (기본 3)")
    ap.add_argument("-W", "--timeout", type=float, default=2.0)
    ap.add_argument("--no-resolve", action="store_true", help="이름을 되찾지 않는다 (더 빠르다)")
    args = ap.parse_args()

    try:
        dest = socket.gethostbyname(args.host)
    except socket.gaierror as exc:
        print(f"이름을 풀지 못했다: {exc}", file=sys.stderr)
        return 1

    sock, how = open_socket()
    ident = os.getpid() & 0xFFFF
    print(f"traceroute {args.host} ({dest}), 최대 {args.max_hops}홉 — 소켓: {how}")

    seq = 0
    for ttl in range(1, args.max_hops + 1):
        addrs, times, done = [], [], False
        for _ in range(args.queries):
            seq += 1
            addr, rtt, reached = probe(sock, dest, ttl, seq, ident, args.timeout)
            if addr:
                addrs.append(addr)
                times.append(f"{rtt:.2f}ms")
            else:
                times.append("*")
            done = done or reached

        if addrs:
            addr = addrs[0]
            name = None if args.no_resolve else resolve_name(addr)
            label = f"{name} ({addr})" if name else addr
        else:
            label = "* (답이 없다)"
        print(f"{ttl:2d}  {label:<52} {'  '.join(times)}")

        if done:
            print(f"\n{args.host} 에 {ttl}홉 만에 닿았다.")
            break
    else:
        print(f"\n{args.max_hops}홉 안에 닿지 못했다. -m 을 올려 다시 해 본다.")

    sock.close()
    print("\n읽는 법")
    print("  *만 나오는 줄은 그 라우터가 ICMP를 돌려주지 않도록 설정된 곳이다.")
    print("  경로에서 사라진 것이 아니라 대답만 안 하는 것이다.")
    print("  같은 목적지에 여러 번 돌려 경로가 바뀌는지 보면, 경로를 미리 정하지 않는다는")
    print("  사실을 눈으로 확인할 수 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
