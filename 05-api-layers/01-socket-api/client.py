#!/usr/bin/env python3
"""소켓 API 클라이언트. 규약을 내가 알고 있어야 쓸 수 있다.

이 클라이언트는 서버와 같은 약속을 공유한다. "GET을 보내면 OK 뒤에 값이
온다"는 것을 코드에 박아 두었다. 서버가 규약을 바꾸면 여기도 고쳐야 한다.
자기 설명(self-describing)이 없는 API의 대가다.

    python3 client.py get
    python3 client.py set 23.5
    python3 client.py bench 100
"""

import argparse
import socket
import sys
import time


def call(sock, command):
    """명령 한 줄을 보내고 답 한 줄을 받는다. (답, 보낸 바이트, 받은 바이트)"""
    raw = (command + "\n").encode()
    sock.sendall(raw)
    reply = b""
    while not reply.endswith(b"\n"):
        chunk = sock.recv(1024)
        if not chunk:
            break
        reply += chunk
    return reply.decode(errors="replace").strip(), len(raw), len(reply)


def main():
    ap = argparse.ArgumentParser(description="소켓 API 클라이언트")
    ap.add_argument("command", choices=["get", "set", "bench"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    args = ap.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
        return 1

    with sock:
        if args.command == "bench":
            n = int(args.value or 100)
            started = time.time()
            sent = got = 0
            for _ in range(n):
                _, s, g = call(sock, "GET")
                sent += s
                got += g
            elapsed = time.time() - started
            print(f"{n}번 요청 — {elapsed * 1000:.1f}ms, 초당 {n / elapsed:.0f}회")
            print(f"오간 바이트 합계 {sent + got} (보냄 {sent}, 받음 {got})")
            print(f"한 번당 {(sent + got) / n:.1f}바이트")
            print("연결 하나를 계속 쓴다. 매번 새로 붙는 HTTP와 여기서 갈린다.")
            return 0

        command = "GET" if args.command == "get" else f"SET {args.value}"
        if args.command == "set" and args.value is None:
            print("set에는 값이 필요하다. 예: python3 client.py set 23.5", file=sys.stderr)
            return 1

        started = time.time()
        reply, sent, got = call(sock, command)
        elapsed = (time.time() - started) * 1000

        print(f"보냄: {command!r} ({sent}바이트)")
        print(f"받음: {reply!r} ({got}바이트)")
        print(f"왕복 {elapsed:.2f}ms, 오간 바이트 {sent + got}")
        print()
        print("이 계층에서 내가 한 일")
        print("  줄바꿈으로 메시지 경계를 찾았다")
        print("  OK/ERR를 직접 갈라 읽었다")
        print("  값을 문자열에서 뽑아냈다")
        print("  서버 규약을 코드에 박아 두었다")
        call(sock, "QUIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
