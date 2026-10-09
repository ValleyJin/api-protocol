#!/usr/bin/env python3
"""GraphQL 클라이언트. 필요한 필드만 골라 받는다.

같은 자원을 REST로 받을 때와 바이트 수를 견준다. 필드를 하나만 고르면
응답이 눈에 띄게 줄어든다. 이것이 GraphQL을 쓰는 가장 큰 까닭이다.

    python3 client.py one          # temperature 하나만
    python3 client.py all          # 필드 넷 모두
    python3 client.py set 24.5     # 뮤테이션
    python3 client.py compare      # REST와 견준다
    python3 client.py bad          # 없는 필드를 골라 본다
"""

import argparse
import http.client
import json
import sys
import time

QUERIES = {
    "one": '{ sensor(id:"living-room") { temperature } }',
    "all": '{ sensor(id:"living-room") { id temperature unit ts } }',
    "bad": '{ sensor(id:"living-room") { temperature humidity } }',
}


def call(host, port, query):
    body = json.dumps({"query": query}).encode()
    conn = http.client.HTTPConnection(host, port, timeout=5)
    started = time.time()
    conn.request("POST", "/graphql", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    elapsed = (time.time() - started) * 1000
    conn.close()
    return resp.status, data, len(body), elapsed


def show(label, host, port, query):
    status, data, sent, ms = call(host, port, query)
    print(f"  질의: {query}")
    print(f"  보낸 본문 {sent}바이트 → 받은 본문 {len(data)}바이트, HTTP {status}, {ms:.1f}ms")
    print(f"  응답: {data.decode('utf-8', 'replace')}")
    return len(data)


def main():
    ap = argparse.ArgumentParser(description="GraphQL 클라이언트")
    ap.add_argument("command", choices=["one", "all", "set", "bad", "compare"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9300)
    ap.add_argument("--rest-port", type=int, default=9200)
    args = ap.parse_args()

    try:
        if args.command in QUERIES:
            show(args.command, args.host, args.port, QUERIES[args.command])
            if args.command == "bad":
                print()
                print("  HTTP 상태는 200인데 본문에 errors가 들어 있다.")
                print("  GraphQL은 오류를 HTTP 상태 코드로 알리지 않는 것이 보통이다.")
                print("  REST에서 400이나 404로 걸러지던 것이 여기서는 본문 안으로 들어온다.")
                print("  그래서 앞단의 프록시나 모니터링 도구가 오류를 알아채지 못한다.")
            return 0

        if args.command == "set":
            if args.value is None:
                print("set에는 값이 필요하다.", file=sys.stderr)
                return 1
            query = f'mutation {{ setTemperature(id:"living-room", value:{float(args.value)}) {{ temperature ts }} }}'
            show("set", args.host, args.port, query)
            print()
            print("  뮤테이션도 같은 엔드포인트에 POST로 보낸다. REST라면 PUT으로 보냈을 것이다.")
            return 0

        # compare
        print("=" * 66)
        print("GraphQL — 필드 하나만 고른다")
        print("=" * 66)
        one = show("one", args.host, args.port, QUERIES["one"])
        print()
        print("=" * 66)
        print("GraphQL — 필드를 모두 고른다")
        print("=" * 66)
        full = show("all", args.host, args.port, QUERIES["all"])
        print()

        print("=" * 66)
        print("REST — 서버가 정한 필드가 모두 온다")
        print("=" * 66)
        try:
            conn = http.client.HTTPConnection(args.host, args.rest_port, timeout=3)
            conn.request("GET", "/sensors/living-room")
            resp = conn.getresponse()
            rest = resp.read()
            conn.close()
            print(f"  GET /sensors/living-room → 본문 {len(rest)}바이트")
            print(f"  응답: {rest.decode('utf-8', 'replace')}")
            rest_len = len(rest)
        except OSError:
            print("  REST 서버가 안 떠 있다. 03-rest-api/server.py 를 띄우면 견줄 수 있다.")
            rest_len = None
        print()

        print("정리")
        print(f"  GraphQL 필드 하나 : 응답 {one}바이트")
        print(f"  GraphQL 필드 넷   : 응답 {full}바이트")
        if rest_len:
            print(f"  REST              : 응답 {rest_len}바이트 (고를 수 없다)")
        print("  값 하나만 필요한 화면에서는 GraphQL이 덜 받는다.")
        print("  대신 질의를 본문에 실어 보내므로 요청은 REST보다 크다.")
        print("  그리고 POST라서 HTTP 캐시가 듣지 않는다. 얻는 것과 잃는 것이 함께 있다.")
        return 0
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
