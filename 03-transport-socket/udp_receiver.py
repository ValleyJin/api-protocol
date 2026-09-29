#!/usr/bin/env python3
"""소켓 API만으로 만든 UDP 수신기.

TCP 서버와 견줘 보면 빠진 것이 눈에 띈다. listen()도 accept()도 없다.
연결이라는 것이 없으니 맺을 것도 없고 받을 것도 없다.

    socket()     SOCK_DGRAM으로 만든다
    bind()       포트를 붙인다. 받는 쪽은 이것이 반드시 필요하다
    recvfrom()   데이터와 함께 "누가 보냈는지"도 같이 받는다

recv()가 아니라 recvfrom()인 이유가 여기 있다. 연결이 없으니 소켓만 봐서는
상대가 누군지 알 수 없다. 그래서 받을 때마다 보낸 쪽 주소를 함께 알려 준다.

    python3 udp_receiver.py
"""

import argparse
import socket


def main():
    ap = argparse.ArgumentParser(description="UDP 수신기")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--echo", action="store_true", help="받은 것을 되돌려 보낸다")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    print(f"[수신] {args.host}:{args.port} 에서 기다린다. 멈추려면 Ctrl+C")
    print("[수신] netstat -an 으로 보면 상태 칸이 비어 있다. UDP에는 연결 상태가 없다.")

    count = 0
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            count += 1
            print(f"[수신] {count}번째: {addr[0]}:{addr[1]} 에서 {len(data)}바이트 — {data[:60]!r}")
            if args.echo:
                sock.sendto(data, addr)
    except KeyboardInterrupt:
        print(f"\n[수신] 멈춘다. 모두 {count}개를 받았다.")
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
