#!/usr/bin/env python3
"""요청 줄과 헤더를 직접 파싱하는 최소 HTTP 서버.

http.server를 쓰지 않는다. 소켓에서 바이트를 읽어 HTTP 메시지를 직접 갈라
읽는다. 프레임워크가 무엇을 대신 해 주고 있었는지 여기서 드러난다.

공통 과제(센서 값 올리고 읽기)를 HTTP로 구현한 것이기도 하다.

    GET  /sensors/living-room/temperature   최근 값을 읽는다
    PUT  /sensors/living-room/temperature   값을 올린다 (본문에 JSON)

    python3 minimal_server.py
    # 다른 창에서
    python3 raw_client.py --port 8080 127.0.0.1 /sensors/living-room/temperature
    curl -X PUT -d '{"temperature":22.5}' localhost:8080/sensors/living-room/temperature
"""

import argparse
import json
import pathlib
import socket
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.sensor import PATH, encode_json, reading  # noqa: E402

STATE = {"latest": reading(21.0)}
LOCK = threading.Lock()


def parse_request(raw):
    """HTTP 요청 바이트를 (메서드, 경로, 헤더, 본문)으로 가른다."""
    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        return None
    head, body = raw[:sep].decode(errors="replace"), raw[sep + 4:]
    lines = head.split("\r\n")
    parts = lines[0].split()
    if len(parts) < 3:
        return None
    method, path, version = parts[0], parts[1], parts[2]

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return method, path, version, headers, body


def build_response(status, body, content_type="application/json"):
    """응답 바이트를 조립한다. 요청과 똑같은 꼴이다. 첫 줄과 헤더와 빈 줄과 본문."""
    reasons = {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found",
               405: "Method Not Allowed", 411: "Length Required"}
    lines = [
        f"HTTP/1.1 {status} {reasons.get(status, '')}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "Server: minimal-socket-server/1.0",
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def handle(conn, addr, verbose):
    with conn:
        conn.settimeout(5)
        raw = b""
        # 헤더가 다 올 때까지 읽는다. TCP는 경계를 안 지켜 주니 직접 찾아야 한다.
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                return
            raw += chunk

        parsed = parse_request(raw)
        if not parsed:
            conn.sendall(build_response(400, b'{"error":"bad request"}'))
            return
        method, path, version, headers, body = parsed

        # Content-Length 만큼 본문이 다 왔는지 확인한다. 이것도 직접 해야 한다.
        want = int(headers.get("content-length", 0))
        while len(body) < want:
            chunk = conn.recv(4096)
            if not chunk:
                break
            body += chunk

        if verbose:
            print(f"[서버] {addr[0]}:{addr[1]} {method} {path} {version} "
                  f"헤더 {len(headers)}개 본문 {len(body)}바이트")

        if path != PATH:
            conn.sendall(build_response(404, b'{"error":"no such sensor"}'))
            return

        if method == "GET":
            with LOCK:
                payload = encode_json(STATE["latest"])
            conn.sendall(build_response(200, payload))
        elif method in ("PUT", "POST"):
            try:
                incoming = json.loads(body or b"{}")
            except json.JSONDecodeError:
                conn.sendall(build_response(400, b'{"error":"body is not JSON"}'))
                return
            # float() 이 터지면 응답을 아예 못 내고 연결이 끊긴다. 받는 자리에서 막는다.
            # inf 와 nan 은 reading() 이 ValueError 로 돌려준다.
            try:
                value = float(incoming.get("temperature", 0))
                with LOCK:
                    STATE["latest"] = reading(value)
                    payload = encode_json(STATE["latest"])
            except (TypeError, ValueError) as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
                conn.sendall(build_response(400, body))
                return
            print(f"[서버] 값을 올렸다: {STATE['latest']['temperature']}C")
            conn.sendall(build_response(201, payload))
        else:
            conn.sendall(build_response(405, b'{"error":"method not allowed"}'))


def main():
    ap = argparse.ArgumentParser(description="직접 파싱하는 최소 HTTP 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(16)
    print(f"[서버] http://{args.host}:{args.port}{PATH}")
    print("[서버] GET으로 읽고 PUT으로 올린다. 멈추려면 Ctrl+C")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle, args=(conn, addr, not args.quiet), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
