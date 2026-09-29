#!/usr/bin/env python3
"""WebSocket 서버. 핸드셰이크와 프레임을 직접 다룬다.

공통 과제를 WebSocket으로 구현한 것이다. 다른 프로토콜과 결정적으로 다른 점은
**서버가 먼저 말을 건다**는 것이다. HTTP와 CoAP에서는 값을 알고 싶으면 클라이언트가
물어야 했다. 여기서는 값이 바뀌면 서버가 밀어 준다.

    클라이언트 → 핸드셰이크 한 번
    서버       → 101 Switching Protocols
    서버       → {"temperature":21.3}   값이 바뀔 때마다
    서버       → {"temperature":21.5}
    클라이언트 → {"set":23.0}            아무 때나 보내도 된다

    python3 server.py
    python3 server.py --interval 0.5
"""

import argparse
import pathlib
import socket
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ws  # noqa: E402
from common.sensor import encode_json, reading  # noqa: E402

STATE = {"latest": reading(21.0)}


def handshake(conn, verbose):
    """HTTP 요청을 읽고 101로 답한다. 여기까지가 HTTP다."""
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = conn.recv(4096)
        if not chunk:
            return False
        raw += chunk

    request_line, headers = ws.parse_http_headers(raw)
    if verbose:
        print(f"[서버] 핸드셰이크 요청 {len(raw)}바이트")
        print(f"       {request_line}")
        print(f"       Upgrade: {headers.get('upgrade')}   "
              f"Sec-WebSocket-Key: {headers.get('sec-websocket-key')}")

    key = headers.get("sec-websocket-key")
    if headers.get("upgrade", "").lower() != "websocket" or not key:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return False

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {ws.accept_key(key)}\r\n\r\n"
    ).encode()
    conn.sendall(response)
    if verbose:
        print(f"[서버] 101 응답 {len(response)}바이트 — 여기서부터 HTTP가 아니다")
        print(f"       Accept = base64(sha1(key + GUID)) = {ws.accept_key(key)}")
    return True


def push_loop(conn, interval, stop, verbose):
    """값이 바뀔 때마다 서버가 먼저 보낸다."""
    sent = 0
    while not stop.is_set():
        time.sleep(interval)
        if stop.is_set():
            break
        STATE["latest"] = reading()
        payload = encode_json(STATE["latest"])
        frame = ws.encode_frame(payload)   # 서버가 보내는 프레임은 마스킹하지 않는다
        try:
            conn.sendall(frame)
        except OSError:
            break
        sent += 1
        if verbose:
            print(f"[서버] 밀어 보냄 {sent}: 프레임 {len(frame)}바이트 "
                  f"(헤더 {len(frame) - len(payload)} + 본문 {len(payload)})")


def handle(conn, addr, interval, verbose):
    with conn:
        if not handshake(conn, verbose):
            return
        print(f"[서버] {addr[0]}:{addr[1]} 연결됨. 값을 밀어 보내기 시작한다.")

        stop = threading.Event()
        pusher = threading.Thread(target=push_loop, args=(conn, interval, stop, verbose),
                                  daemon=True)
        pusher.start()

        buffer = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    frame, buffer = ws.decode_frame(buffer)
                    if frame is None:
                        break
                    if frame["opcode"] == ws.OP_CLOSE:
                        print(f"[서버] {addr[0]}:{addr[1]} 닫기 프레임을 보냈다")
                        conn.sendall(ws.encode_frame(b"", ws.OP_CLOSE))
                        raise ConnectionError
                    if frame["opcode"] == ws.OP_PING:
                        conn.sendall(ws.encode_frame(frame["payload"], ws.OP_PONG))
                        continue
                    if frame["opcode"] == ws.OP_TEXT:
                        text = frame["payload"].decode(errors="replace")
                        print(f"[서버] 받음: {text!r} "
                              f"(마스킹됨={frame['masked']}, {frame['size']}바이트)")
                        if not frame["masked"]:
                            print("       클라이언트가 보낸 프레임인데 마스킹이 안 됐다. "
                                  "규약 위반이다.")
        except (OSError, ConnectionError):
            pass
        finally:
            stop.set()
            print(f"[서버] {addr[0]}:{addr[1]} 끊김")


def main():
    ap = argparse.ArgumentParser(description="직접 만든 WebSocket 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--interval", type=float, default=1.0, help="값을 미는 간격(초)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(16)
    print(f"[서버] ws://{args.host}:{args.port}/ws — 멈추려면 Ctrl+C", flush=True)

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle, args=(conn, addr, args.interval, not args.quiet),
                             daemon=True).start()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
