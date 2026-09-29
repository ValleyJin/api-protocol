#!/usr/bin/env python3
"""REST 클라이언트. 자원 URL과 HTTP 메서드만 알면 된다.

01-socket-api/client.py 는 서버가 만든 규약을 알아야 했다. 여기서는 몰라도 된다.
GET은 읽기, PUT은 바꾸기라는 약속이 HTTP에 이미 있다. 상태 코드도 마찬가지다.
200은 됐다, 404는 없다, 405는 그 메서드는 안 된다.

    python3 client.py get
    python3 client.py set 23.5
    python3 client.py list
    python3 client.py explore        # 메서드를 두루 눌러 보며 응답을 확인한다
"""

import argparse
import http.client
import json
import sys
import time


def request(host, port, method, path, payload=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    started = time.time()
    conn.request(method, path, body, headers)
    resp = conn.getresponse()
    data = resp.read()
    elapsed = (time.time() - started) * 1000
    conn.close()
    return resp.status, dict(resp.getheaders()), data, elapsed


def main():
    ap = argparse.ArgumentParser(description="REST 클라이언트")
    ap.add_argument("command", choices=["get", "set", "list", "explore"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9200)
    args = ap.parse_args()

    base = "/sensors/living-room"
    try:
        if args.command == "get":
            status, headers, data, ms = request(args.host, args.port, "GET", base)
        elif args.command == "list":
            status, headers, data, ms = request(args.host, args.port, "GET", "/sensors")
        elif args.command == "set":
            if args.value is None:
                print("set에는 값이 필요하다.", file=sys.stderr)
                return 1
            status, headers, data, ms = request(args.host, args.port, "PUT", base,
                                                {"temperature": float(args.value)})
        else:
            print("메서드를 두루 눌러 본다. 상태 코드가 무엇을 말하는지 본다.\n")
            for method, path, payload in [
                ("GET", base, None),
                ("PUT", base, {"temperature": 22.2}),
                ("PUT", base, {"wrong": 1}),
                ("DELETE", base, None),
                ("GET", "/sensors/kitchen", None),
            ]:
                status, headers, data, ms = request(args.host, args.port, method, path, payload)
                note = {200: "됐다", 400: "요청이 잘못됐다", 404: "그런 자원이 없다",
                        405: f"그 메서드는 안 된다 (되는 것: {headers.get('Allow')})"}
                print(f"  {method:<6} {path:<28} → {status} {note.get(status, '')}")
                print(f"         {data.decode(errors='replace')[:70]}")
            print()
            print("상태 코드만 보고도 무슨 일이 났는지 안다. 내가 정한 규약이 아니라")
            print("HTTP가 정해 둔 것이라, 남이 만든 도구도 그대로 알아듣는다.")
            return 0
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
        return 1

    print(f"상태 {status}, {ms:.1f}ms, 본문 {len(data)}바이트")
    print(json.dumps(json.loads(data), ensure_ascii=False, indent=2))
    print()
    print("이 계층에서 라이브러리가 대신 해 준 일")
    print("  소켓을 열고 닫았다")
    print("  요청 줄과 헤더를 조립했다")
    print("  Content-Length를 세어 붙였다")
    print("  응답을 상태 줄, 헤더, 본문으로 갈라 주었다")
    print("  내가 한 일은 메서드와 경로를 고르고 JSON을 읽은 것뿐이다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
