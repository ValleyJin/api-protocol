#!/usr/bin/env python3
"""Webhook을 받는 쪽. 받으려면 나도 서버여야 한다.

이 파일이 Webhook의 값과 대가를 한꺼번에 보여 준다.

    값  : 평소에 아무 연결도 없다. 값이 바뀔 때만 한 번 불린다.
    대가: 공개된 주소로 서버를 띄워야 한다. 방화벽 뒤에서는 못 받는다.
          아무나 내 주소를 알면 가짜 알림을 보낼 수 있다. 그래서 서명 확인이 필요하다.

--verify 를 켜면 서명 확인을 흉내 낸다. 실무에서는 보내는 쪽이 본문을 공유
비밀키로 HMAC 해 헤더에 넣고, 받는 쪽이 같은 계산을 해서 맞춰 본다. GitHub의
X-Hub-Signature-256 이 그것이다.

    python3 source.py &
    python3 receiver.py
    curl -X PUT -d '{"temperature":25.0}' localhost:9600/sensors/living-room
"""

import argparse
import hashlib
import hmac
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECEIVED = []
SECRET = b"shared-secret-for-demo"


class Handler(BaseHTTPRequestHandler):
    server_version = "webhook-receiver/1.0"

    def log_message(self, fmt, *args):
        pass    # 알림만 찍고 접속 로그는 끈다

    def do_POST(self):
        if self.path != "/hook":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        if self.server.verify:
            # 보내는 쪽이 붙였어야 할 서명. 이 실습의 source.py 는 붙이지 않으므로
            # 일부러 실패하는 모습을 보게 된다. 그것이 요점이다.
            got = self.headers.get("X-Signature-256", "")
            want = "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(got, want):
                print(f"[받는쪽] 서명이 맞지 않아 버린다. 받은 값={got or '(없음)'}", flush=True)
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        RECEIVED.append(payload)
        attempt = self.headers.get("X-Attempt", "1")
        data = payload.get("data", {})
        print(f"[받는쪽] {len(RECEIVED)}번째 알림: {data.get('temperature')}"
              f"{data.get('unit', '')}  (본문 {length}바이트, {attempt}번째 시도)", flush=True)

        # 2xx로 답해야 보내는 쪽이 성공으로 여긴다. 안 그러면 다시 보낸다.
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


def register(source, callback):
    body = json.dumps({"callback": callback}).encode()
    request = urllib.request.Request(source + "/subscriptions", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser(description="Webhook을 받는 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9601)
    ap.add_argument("--source", default="http://127.0.0.1:9600")
    ap.add_argument("--verify", action="store_true", help="서명을 확인한다 (일부러 실패해 본다)")
    ap.add_argument("--timeout", type=float, default=0, help="이 초만큼만 기다린다")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.verify = args.verify
    callback = f"http://{args.host}:{args.port}/hook"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[받는쪽] {callback} 에서 알림을 기다린다", flush=True)

    try:
        result = register(args.source, callback)
        print(f"[받는쪽] 등록했다. 지금 등록된 곳 {result['count']}개", flush=True)
    except (urllib.error.URLError, OSError) as exc:
        print(f"등록하지 못했다: {exc}", file=sys.stderr)
        print("먼저 서비스를 띄운다: python3 source.py", file=sys.stderr)
        return 1

    if args.verify:
        print("[받는쪽] 서명 확인을 켰다. source.py 는 서명을 안 붙이므로 모두 버려진다.",
              flush=True)
        print("[받는쪽] 서명 없는 Webhook이 왜 위험한지 그대로 드러난다.", flush=True)

    print("[받는쪽] 다른 창에서 값을 바꿔 본다:", flush=True)
    print(f"  curl -X PUT -d '{{\"temperature\":25.0}}' {args.source}/sensors/living-room",
          flush=True)
    print("[받는쪽] 멈추려면 Ctrl+C\n", flush=True)

    started = time.time()
    try:
        while True:
            if args.timeout and time.time() - started > args.timeout:
                print(f"\n{args.timeout}초가 지났다. 받은 알림 {len(RECEIVED)}건.")
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        print(f"\n[받는쪽] 멈춘다. 받은 알림 {len(RECEIVED)}건.")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
