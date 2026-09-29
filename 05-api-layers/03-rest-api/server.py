#!/usr/bin/env python3
"""REST API 서버. 자원을 URL로 드러내고 HTTP 메서드로 다룬다.

01-socket-api와 견줘 보면 무엇이 달라졌는지 분명하다.

    소켓 API   GET\\n                          내가 만든 명령
    REST       GET /sensors/living-room        모두가 아는 메서드 + URL

REST의 요점은 '명령'이 아니라 '자원'을 드러내는 것이다. 무엇을 할지는 HTTP
메서드가 이미 정해 두었으니, 나는 무엇에 할지만 URL로 적으면 된다.

    GET    /sensors                    목록을 읽는다
    GET    /sensors/living-room        하나를 읽는다
    PUT    /sensors/living-room        값을 통째로 바꾼다
    DELETE /sensors/living-room        지운다 (여기서는 405로 막는다)

덕분에 캐시, 프록시, 로드밸런서가 내 규약을 몰라도 일을 한다. GET은 안전하고
PUT은 여러 번 해도 결과가 같다는 약속이 HTTP에 이미 들어 있기 때문이다.

이 서버는 표준 라이브러리 http.server 를 쓴다. 04-application/http 에서는
같은 일을 소켓으로 직접 했다. 둘을 견주면 라이브러리가 무엇을 대신 해 주는지
보인다.

    python3 server.py
"""

import argparse
import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.store import get, set_value  # noqa: E402

BASE = "/sensors"
SENSOR_ID = "living-room"


class Handler(BaseHTTPRequestHandler):
    server_version = "rest-api/1.0"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            print(f"[서버] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, status, payload, extra_headers=None):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # REST에서 흔히 쓰는 헤더들. 캐시와 동시성 제어를 HTTP에 맡기는 자리다.
        self.send_header("Cache-Control", "no-cache")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == BASE:
            self._send(200, {"sensors": [SENSOR_ID], "count": 1})
        elif self.path == f"{BASE}/{SENSOR_ID}":
            self._send(200, get())
        else:
            self._send(404, {"error": "not found", "path": self.path})

    def do_PUT(self):
        if self.path != f"{BASE}/{SENSOR_ID}":
            self._send(404, {"error": "not found", "path": self.path})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            value = float(payload["temperature"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._send(400, {"error": "본문에 temperature 값이 있어야 한다"})
            return
        result = set_value(value)
        # 자원의 위치를 알려 준다. REST에서 자주 쓰는 방식이다.
        self._send(200, result, {"Location": f"{BASE}/{SENSOR_ID}"})

    def do_DELETE(self):
        self._send(405, {"error": "센서는 지울 수 없다"}, {"Allow": "GET, PUT"})


def main():
    ap = argparse.ArgumentParser(description="REST API 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9200)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.verbose = not args.quiet
    print(f"[서버] http://{args.host}:{args.port}{BASE}/{SENSOR_ID}", flush=True)
    print("[서버] GET으로 읽고 PUT으로 올린다. 멈추려면 Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
