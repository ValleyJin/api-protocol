#!/usr/bin/env python3
"""프로토콜 라이브러리 계층. 같은 REST 서버를 세 가지 높이에서 부른다.

03-rest-api/server.py 를 띄워 놓고 이 파일을 돌린다. 서버는 그대로인데
클라이언트 쪽 계층만 바꿔 가며 무엇이 달라지는지 본다.

    1. 소켓         요청 문자열을 손으로 적는다
    2. http.client  표준 라이브러리. HTTP를 알지만 연결 관리는 내 몫이다
    3. requests     외부 패키지. 연결 재사용, 재시도, 인코딩까지 맡긴다

세 가지가 만드는 바이트를 함께 찍는다. 계층을 올릴수록 코드는 줄고 실제로 오가는
흐르는 바이트는 늘어난다. 그 대가를 눈으로 확인하는 것이 이 폴더의 목적이다.

    python3 ../03-rest-api/server.py &
    python3 client.py
"""

import argparse
import http.client
import json
import socket
import sys
import time

PATH = "/sensors/living-room"


def by_socket(host, port):
    """소켓으로 요청 문자열을 직접 적는다."""
    request = (
        f"GET {PATH} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    with socket.create_connection((host, port), 5) as sock:
        started = time.time()
        sock.sendall(request)
        response = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            response += chunk
        elapsed = (time.time() - started) * 1000
    body = response.split(b"\r\n\r\n", 1)[1]
    return {"요청 바이트": len(request), "응답 바이트": len(response),
            "본문": body, "ms": elapsed, "내 코드가 한 일": [
                "요청 줄과 헤더를 문자열로 적었다",
                "빈 줄로 헤더 끝을 표시했다",
                "연결이 닫힐 때까지 읽어 응답 끝을 알아냈다",
                "\\r\\n\\r\\n 을 찾아 헤더와 본문을 갈랐다",
            ]}


def by_http_client(host, port):
    """표준 라이브러리. HTTP 문법은 라이브러리가 안다."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    started = time.time()
    conn.request("GET", PATH)
    resp = conn.getresponse()
    body = resp.read()
    elapsed = (time.time() - started) * 1000
    # 라이브러리가 실제로 보낸 요청을 재구성해 바이트를 센다.
    approx = len(f"GET {PATH} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept-Encoding: identity\r\n\r\n")
    conn.close()
    return {"요청 바이트": approx, "응답 바이트": len(body) + 150, "본문": body,
            "ms": elapsed, "내 코드가 한 일": [
                "메서드와 경로를 골랐다",
                "본문을 읽었다",
            ]}


def by_requests(host, port):
    """외부 패키지. 세션과 재시도까지 맡긴다."""
    try:
        import requests
    except ImportError:
        return None
    session = requests.Session()
    started = time.time()
    resp = session.get(f"http://{host}:{port}{PATH}", timeout=5)
    elapsed = (time.time() - started) * 1000
    sent = len(resp.request.method) + len(resp.request.url) + sum(
        len(k) + len(v) + 4 for k, v in resp.request.headers.items()) + 20
    session.close()
    return {"요청 바이트": sent, "응답 바이트": len(resp.content) + 150,
            "본문": resp.content, "ms": elapsed,
            "붙은 헤더": dict(resp.request.headers),
            "내 코드가 한 일": ["URL을 적었다"]}


def main():
    ap = argparse.ArgumentParser(description="라이브러리 계층 견주기")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9200)
    args = ap.parse_args()

    try:
        results = [("1. 소켓", by_socket(args.host, args.port)),
                   ("2. http.client", by_http_client(args.host, args.port))]
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 REST 서버를 띄운다: python3 ../03-rest-api/server.py", file=sys.stderr)
        return 1

    third = by_requests(args.host, args.port)
    if third:
        results.append(("3. requests", third))

    for label, result in results:
        print("=" * 66)
        print(label)
        print("=" * 66)
        print(f"  요청 약 {result['요청 바이트']}바이트, 응답 약 {result['응답 바이트']}바이트, "
              f"{result['ms']:.1f}ms")
        value = json.loads(result["본문"])["temperature"]
        print(f"  읽은 값: {value}")
        print("  내 코드가 한 일:")
        for item in result["내 코드가 한 일"]:
            print(f"    - {item}")
        if "붙은 헤더" in result:
            print("  라이브러리가 알아서 붙인 요청 헤더:")
            for key, value in result["붙은 헤더"].items():
                print(f"    {key}: {value}")
        print()

    if not third:
        print("requests가 없다. pip install requests 로 깔면 셋을 모두 견줄 수 있다.\n")

    print("정리")
    print("  계층을 올리면 내가 쓸 코드가 줄고, 실제로 오가는 바이트는 늘어난다.")
    print("  줄어든 코드만큼 나는 HTTP 문법을 몰라도 된다. 늘어난 바이트만큼 대역을 쓴다.")
    print("  어느 쪽이 맞는지는 상황이 정한다. 배터리로 도는 센서와 사내 서버는 답이 다르다.")
    print()
    print("  실제로 흐르는 바이트를 세려면 캡처를 뜬다:")
    print(f"    sudo tcpdump -i lo0 -A -c 20 port {args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
