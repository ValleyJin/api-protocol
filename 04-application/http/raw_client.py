#!/usr/bin/env python3
"""소켓에 HTTP 요청 문자열을 직접 써서 보내는 최소 클라이언트.

라이브러리를 쓰지 않는다. HTTP/1.1이 TCP 위에 얹힌 '텍스트 규약'이라는 말이
무슨 뜻인지 여기서 그대로 드러난다. 보내는 것은 그저 아래 글자들이다.

    GET /path HTTP/1.1\\r\\n
    Host: example.com\\r\\n
    Connection: close\\r\\n
    \\r\\n

줄 끝은 \\r\\n이고, 빈 줄 하나가 헤더의 끝을 알린다. 03 폴더에서 본 대로
TCP는 메시지 경계를 지켜 주지 않으니, HTTP가 빈 줄로 경계를 스스로 정한 것이다.

HTTP/2는 이 텍스트를 바이너리 프레임으로 바꿨고, HTTP/3은 TCP 대신 UDP 위
QUIC에서 돈다. 여기서 확인하는 것은 HTTP/1.1이다.

    python3 raw_client.py example.com /
    python3 raw_client.py --port 8080 127.0.0.1 /sensors/living-room/temperature
"""

import argparse
import socket
import sys
import time


def request(host, path, port=80, method="GET", body=None, headers=None, timeout=5):
    """요청을 바이트로 조립해 보내고 응답 원문을 그대로 돌려준다."""
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close",
             "User-Agent: raw-socket-client/1.0"]
    for key, value in (headers or {}).items():
        lines.append(f"{key}: {value}")
    if body is not None:
        lines.append(f"Content-Length: {len(body)}")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode()
    raw = head + (body or b"")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        started = time.time()
        sock.connect((host, port))
        sock.sendall(raw)

        # Connection: close 라고 했으니 서버가 다 보내고 연결을 닫는다.
        # 그 닫힘이 곧 "응답이 끝났다"는 신호다. recv()가 빈 바이트를 돌려준다.
        chunks = []
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
    return raw, b"".join(chunks), (time.time() - started) * 1000


def split_response(response):
    """헤더와 본문을 가른다. 빈 줄 하나가 경계다."""
    sep = response.find(b"\r\n\r\n")
    if sep < 0:
        return response, b""
    return response[:sep], response[sep + 4:]


def main():
    ap = argparse.ArgumentParser(description="소켓으로 직접 HTTP 요청을 보낸다")
    ap.add_argument("host")
    ap.add_argument("path", nargs="?", default="/")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--body", action="store_true", help="본문도 모두 찍는다")
    args = ap.parse_args()

    try:
        sent, response, elapsed = request(args.host, args.path, args.port)
    except OSError as exc:
        print(f"연결하지 못했다: {exc}", file=sys.stderr)
        return 1

    print("=" * 66)
    print("보낸 것 (이 글자 그대로 TCP에 흘려보냈다)")
    print("=" * 66)
    print(sent.decode(errors="replace").replace("\r\n", "⏎\n"), end="")
    print(f"\n→ 요청 {len(sent)}바이트\n")

    head, body = split_response(response)
    print("=" * 66)
    print("돌아온 것")
    print("=" * 66)
    print(head.decode(errors="replace"))
    print()
    if args.body:
        print(body.decode(errors="replace"))
    else:
        preview = body[:300].decode(errors="replace")
        print(f"본문 앞 300바이트:\n{preview}")
    print()
    print(f"응답 전체 {len(response)}바이트 = 헤더 {len(head) + 4} + 본문 {len(body)}")
    print(f"왕복 시간 {elapsed:.1f}ms")
    print()
    print("짚을 것")
    print("  헤더가 본문보다 클 때가 많다. 값 하나를 받으려고 수백 바이트를 쓴다.")
    print("  이 비율을 MQTT, CoAP와 견주는 것이 04 폴더의 공통 과제다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
