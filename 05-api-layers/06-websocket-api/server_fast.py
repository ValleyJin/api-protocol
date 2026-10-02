#!/usr/bin/env python3
"""WebSocket을 API로 쓴다. 요청-응답과 구독을 한 연결에서 함께 한다.

04-application/websocket 은 프로토콜 자체를 뜯어보는 자리였다. 여기서는 그
프로토콜 위에 **API를 얹는다**. 프레임 안에 JSON을 넣고 메시지 종류를 내가 정한다.

    클라이언트 → {"id":1,"method":"get"}
    서버       → {"id":1,"result":{"temperature":21.0}}

    클라이언트 → {"id":2,"method":"subscribe"}
    서버       → {"id":2,"result":"subscribed"}
    서버       → {"event":"reading","data":{...}}     값이 바뀔 때마다

REST와 갈리는 지점이 둘이다. 첫째, 요청에 id를 붙여야 한다. 한 연결에 여러
요청이 떠 있을 수 있어 답이 순서대로 오지 않기 때문이다. HTTP는 연결마다
요청 하나를 맞춰 주지만 여기서는 내 몫이다. 둘째, 서버가 먼저 보내는 event가
있다. REST에는 없는 방향이다.

JSON-RPC 2.0이 바로 이 꼴을 규격으로 정해 둔 것이다. 여기서는 그 뼈대만 쓴다.

    python3 server.py
"""

import argparse
import json
import pathlib
import socket
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "04-application" / "websocket"))

import ws  # noqa: E402
from common.store import get, set_value  # noqa: E402


def handshake(conn):
    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = conn.recv(4096)
        if not chunk:
            return False
        raw += chunk
    _, headers = ws.parse_http_headers(raw)
    key = headers.get("sec-websocket-key")
    if not key:
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        return False
    conn.sendall((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {ws.accept_key(key)}\r\n\r\n"
    ).encode())
    return True


def send_json(conn, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    conn.sendall(ws.encode_frame(body))
    return len(body)


def event_loop(conn, state, verbose):
    """구독한 클라이언트에게 값이 바뀔 때마다 밀어 준다."""
    last = None
    while not state["stop"].is_set():
        time.sleep(0.01)
        if not state["subscribed"]:
            continue
        record = get()
        if record["ts"] == last:
            continue
        last = record["ts"]
        try:
            size = send_json(conn, {"event": "reading", "data": record})
        except OSError:
            return
        if verbose:
            print(f"[서버] event 밀어 보냄 {size}바이트", flush=True)


def handle(conn, addr, verbose):
    with conn:
        if not handshake(conn):
            return
        print(f"[서버] {addr[0]}:{addr[1]} 연결됨", flush=True)
        state = {"subscribed": False, "stop": threading.Event()}
        threading.Thread(target=event_loop, args=(conn, state, verbose), daemon=True).start()

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
                        raise ConnectionError
                    if frame["opcode"] != ws.OP_TEXT:
                        continue
                    try:
                        request = json.loads(frame["payload"])
                    except json.JSONDecodeError:
                        send_json(conn, {"error": "JSON이 아니다"})
                        continue

                    rid, method = request.get("id"), request.get("method")
                    if verbose:
                        print(f"[서버] 요청 id={rid} method={method!r}", flush=True)

                    if method == "get":
                        send_json(conn, {"id": rid, "result": get()})
                    elif method == "set":
                        try:
                            result = set_value(request["params"]["temperature"])
                            send_json(conn, {"id": rid, "result": result})
                        except (KeyError, TypeError, ValueError):
                            send_json(conn, {"id": rid,
                                             "error": "params.temperature 가 있어야 한다"})
                    elif method == "subscribe":
                        state["subscribed"] = True
                        send_json(conn, {"id": rid, "result": "subscribed"})
                        print(f"[서버] {addr[1]} 구독 시작 — 이제 서버가 먼저 보낸다", flush=True)
                    elif method == "unsubscribe":
                        state["subscribed"] = False
                        send_json(conn, {"id": rid, "result": "unsubscribed"})
                    else:
                        send_json(conn, {"id": rid, "error": f"모르는 method: {method}"})
        except (OSError, ConnectionError):
            pass
        finally:
            state["stop"].set()
            print(f"[서버] {addr[0]}:{addr[1]} 끊김", flush=True)


def main():
    ap = argparse.ArgumentParser(description="WebSocket API 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9500)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(16)
    print(f"[서버] ws://{args.host}:{args.port}/ — method: get, set, subscribe", flush=True)
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
