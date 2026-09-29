#!/usr/bin/env python3
"""같은 이름 풀이를 운영체제에 맡기고, 직접 만든 것과 견준다.

query.py는 질의 패킷을 손으로 조립해 8.8.8.8에 직접 보냈다. 여기서는
socket.getaddrinfo() 한 줄로 끝낸다. 그 한 줄 안에서 운영체제가 하는 일이 많다.

    /etc/hosts 를 먼저 본다
    캐시에 있는지 본다
    /etc/resolv.conf 에 적힌 리졸버에 묻는다 (macOS는 시스템 설정)
    검색 도메인을 붙여 다시 물어 본다
    IPv4와 IPv6를 함께 찾고 우선순위를 매긴다 (RFC 6724)

05 폴더에서 다룰 "API 계층"의 좋은 예다. DNS는 4층 프로토콜이지만, 이름 풀이
API는 운영체제가 내준다. 그래서 라이브러리를 깔지 않아도 이름을 풀 수 있다.

    python3 resolve_lib.py example.com
"""

import argparse
import socket
import sys
import time


def main():
    ap = argparse.ArgumentParser(description="운영체제에 이름 풀이를 맡긴다")
    ap.add_argument("name")
    args = ap.parse_args()

    print("=" * 66)
    print("1. socket.gethostbyname — 가장 짧지만 IPv4만 준다")
    print("=" * 66)
    started = time.time()
    try:
        ip = socket.gethostbyname(args.name)
    except socket.gaierror as exc:
        print(f"풀지 못했다: {exc}", file=sys.stderr)
        return 1
    print(f"{args.name} → {ip}   ({(time.time() - started) * 1000:.1f}ms)")
    print()

    print("=" * 66)
    print("2. socket.getaddrinfo — 요즘 쓰는 쪽. IPv4와 IPv6를 함께 준다")
    print("=" * 66)
    started = time.time()
    infos = socket.getaddrinfo(args.name, 80, proto=socket.IPPROTO_TCP)
    elapsed = (time.time() - started) * 1000
    seen = set()
    for family, socktype, proto, canonname, sockaddr in infos:
        family_name = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(family, family)
        if sockaddr[0] in seen:
            continue
        seen.add(sockaddr[0])
        print(f"  {family_name:<5} {sockaddr[0]}")
    print(f"  ({elapsed:.1f}ms, 결과 {len(infos)}개 중 서로 다른 주소 {len(seen)}개)")
    print()

    print("=" * 66)
    print("3. 되돌려 풀기 — 주소에서 이름 찾기 (PTR 레코드)")
    print("=" * 66)
    try:
        host, aliases, addrs = socket.gethostbyaddr(ip)
        print(f"{ip} → {host}")
        print("정방향과 역방향이 꼭 짝을 이루지는 않는다. 서로 다른 관리자가 채우기 때문이다.")
    except (socket.herror, OSError):
        print(f"{ip} 에는 PTR 레코드가 없다. 흔한 일이다.")
    print()

    print("견줄 것")
    print("  코드 줄 수  : query.py 약 200줄 / 여기 한 줄")
    print("  감춰진 것   : 캐시, /etc/hosts, 검색 도메인, IPv6 우선순위, TCP 대체")
    print("  드러나는 것 : TTL, 응답 크기, 어느 서버가 답했는지 — 여기서는 안 보인다")
    print("  둘을 나란히 캡처해 보면 오가는 패킷이 다르다.")
    print("  sudo tcpdump -i en0 -c 10 port 53")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
