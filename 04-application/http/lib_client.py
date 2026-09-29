#!/usr/bin/env python3
"""같은 요청을 라이브러리로 다시 보내고, 직접 만든 것과 견준다.

raw_client.py는 요청 문자열을 손으로 적었다. 여기서는 http.client(표준
라이브러리)와 requests(외부 패키지)로 같은 일을 한다. 코드는 짧아지고
실제로 오가는 바이트는 늘어난다. 라이브러리가 헤더를 알아서 붙이기 때문이다.

이것이 05 폴더에서 계층별로 견줄 내용의 맛보기다. 계층을 올리면 편해지는
대신 무엇이 오가는지 안 보이게 된다.

    python3 lib_client.py example.com /
    python3 lib_client.py --port 8080 127.0.0.1 /sensors/living-room/temperature
"""

import argparse
import http.client
import sys
import time


def with_http_client(host, path, port):
    """표준 라이브러리. 소켓과 HTTP 파싱을 감춰 준다."""
    started = time.time()
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    elapsed = (time.time() - started) * 1000
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, headers, body, elapsed


def with_requests(host, path, port):
    """외부 패키지. 연결 재사용과 재시도, 인코딩까지 감춰 준다."""
    try:
        import requests
    except ImportError:
        return None
    started = time.time()
    resp = requests.get(f"http://{host}:{port}{path}", timeout=5)
    return resp.status_code, dict(resp.headers), resp.content, (time.time() - started) * 1000


def main():
    ap = argparse.ArgumentParser(description="라이브러리로 같은 요청을 보낸다")
    ap.add_argument("host")
    ap.add_argument("path", nargs="?", default="/")
    ap.add_argument("--port", type=int, default=80)
    args = ap.parse_args()

    print("=" * 66)
    print("1. http.client — 표준 라이브러리")
    print("=" * 66)
    try:
        status, headers, body, elapsed = with_http_client(args.host, args.path, args.port)
    except OSError as exc:
        print(f"실패했다: {exc}", file=sys.stderr)
        return 1
    print(f"상태 {status}, 본문 {len(body)}바이트, {elapsed:.1f}ms")
    print(f"코드 세 줄이면 끝난다. raw_client.py는 40줄이 넘는다.")
    print(f"응답 헤더 {len(headers)}개를 사전으로 바로 준다. 파싱은 라이브러리가 했다.")
    print()

    print("=" * 66)
    print("2. requests — 외부 패키지")
    print("=" * 66)
    result = with_requests(args.host, args.path, args.port)
    if result is None:
        print("requests가 깔려 있지 않다. pip install requests 로 깔면 견줘 볼 수 있다.")
    else:
        status, headers, body, elapsed = result
        print(f"상태 {status}, 본문 {len(body)}바이트, {elapsed:.1f}ms")
        print("한 줄이면 된다. 대신 요청에 User-Agent, Accept-Encoding, Connection 헤더를")
        print("알아서 붙인다. 내가 안 적은 바이트가 실제로 오간다는 뜻이다.")
    print()

    print("견줄 것")
    print("  코드 줄 수  : 소켓 > http.client > requests")
    print("  오가는 바이트: 소켓 < http.client ≤ requests")
    print("  보이는 정도 : 소켓 > http.client > requests")
    print("  캡처를 떠서 요청 바이트를 실제로 세어 보면 이 순서가 눈에 보인다.")
    print("  sudo tcpdump -i lo0 -A -c 10 port 8080")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
