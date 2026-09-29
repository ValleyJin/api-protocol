#!/usr/bin/env python3
"""가장 낮은 계층. 소켓 API만으로 내 규약을 직접 만든다.

HTTP도 MQTT도 쓰지 않는다. 줄 단위 텍스트 규약을 내가 정한다.

    GET\\n              →  OK 21.0\\n
    SET 23.5\\n         →  OK 23.5\\n
    (그 밖)             →  ERR unknown command\\n

여기서 직접 정해야 하는 것이 무엇인지 세어 보면 상위 계층 API가 무엇을 대신
해 주는지 드러난다.

    메시지 경계    줄바꿈으로 정했다. TCP가 안 지켜 주니 내 몫이다
    오류 표현      OK/ERR 로 정했다. HTTP의 상태 코드에 해당한다
    자료 모양      공백으로 나눈 텍스트. JSON도 protobuf도 아니다
    판본 관리      없다. 규약을 바꾸면 양쪽을 같이 고쳐야 한다
    인증           없다
    재시도         없다

    python3 server.py
"""

import argparse
import pathlib
import socket
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.store import get, set_value  # noqa: E402


def handle(conn, addr, verbose):
    with conn:
        conn.settimeout(30)
        buffer = b""
        while True:
            try:
                chunk = conn.recv(1024)
            except socket.timeout:
                return
            if not chunk:
                return
            buffer += chunk

            # 줄바꿈이 나올 때까지 모은다. 이것이 '메시지 경계를 직접 정한다'는 말의 뜻이다.
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                command = line.decode(errors="replace").strip()
                if verbose:
                    print(f"[서버] {addr[1]} → {command!r}")

                parts = command.split()
                if not parts:
                    continue
                if parts[0].upper() == "GET":
                    reply = f"OK {get()['temperature']}\n"
                elif parts[0].upper() == "SET" and len(parts) == 2:
                    try:
                        reply = f"OK {set_value(float(parts[1]))['temperature']}\n"
                    except ValueError:
                        reply = "ERR not a number\n"
                elif parts[0].upper() == "QUIT":
                    conn.sendall(b"OK bye\n")
                    return
                else:
                    reply = "ERR unknown command\n"
                conn.sendall(reply.encode())
                if verbose:
                    print(f"[서버] {addr[1]} ← {reply.strip()!r} ({len(reply)}바이트)")


def main():
    ap = argparse.ArgumentParser(description="소켓 API로 만든 센서 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(16)
    print(f"[서버] {args.host}:{args.port} — 줄 단위 텍스트 규약. 멈추려면 Ctrl+C", flush=True)
    print("[서버] 써 볼 명령: GET / SET 23.5 / QUIT", flush=True)

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle, args=(conn, addr, not args.quiet),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
