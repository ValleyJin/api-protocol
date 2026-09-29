#!/usr/bin/env python3
"""Webhook 방식의 센서 서비스. 값이 바뀌면 **내가 상대를 부른다**.

지금까지 일곱 가지는 모두 클라이언트가 서버를 불렀다. Webhook은 방향이 뒤집힌다.

    REST      앱 → 서버 : "값 뭐야?"          (앱이 계속 물어야 한다)
    WebSocket 앱 ↔ 서버 : 연결을 붙들고 있다  (연결 수만큼 자원을 쓴다)
    Webhook   서버 → 앱 : "값 바뀌었어"       (평소에는 아무 연결도 없다)

그래서 Webhook은 받는 쪽도 서버여야 한다. 공개된 URL이 있어야 내가 부를 수
있기 때문이다. 이것이 Webhook의 가장 큰 제약이다. 방화벽 뒤의 모바일 앱은
Webhook을 받을 수 없다.

    POST /subscriptions   {"callback": "http://..."}   나를 불러 달라고 등록한다
    PUT  /sensors/living-room  {"temperature": 23.0}   값을 올리면 등록된 곳을 모두 부른다

    python3 source.py
"""

import argparse
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.store import get, set_value  # noqa: E402

SUBSCRIBERS = []
LOCK = threading.Lock()


def notify_all(record, verbose):
    """등록된 곳을 차례로 부른다. 실패하면 다시 해야 한다."""
    with LOCK:
        targets = list(SUBSCRIBERS)
    if not targets:
        if verbose:
            print("[서비스] 등록된 곳이 없다. 부를 데가 없다.", flush=True)
        return

    body = json.dumps({"event": "reading", "data": record}).encode()
    for url in targets:
        # 재시도를 세 번 한다. 받는 쪽이 잠깐 죽어 있을 수 있다.
        # 이것이 Webhook에서 보내는 쪽이 떠안는 짐이다. REST 서버에는 없던 일이다.
        for attempt in range(1, 4):
            request = urllib.request.Request(url, data=body, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "X-Event": "reading",
                                                      "X-Attempt": str(attempt)})
            try:
                with urllib.request.urlopen(request, timeout=3) as resp:
                    print(f"[서비스] {url} 호출 성공 ({resp.status}, {attempt}번째 시도)",
                          flush=True)
                break
            except (urllib.error.URLError, OSError) as exc:
                print(f"[서비스] {url} 호출 실패 ({attempt}/3): {exc}", flush=True)
        else:
            print(f"[서비스] {url} 를 세 번 다 실패했다. 이 알림은 사라진다.", flush=True)
            print("[서비스] 진짜 서비스라면 여기서 큐에 쌓아 두고 나중에 다시 보낸다.",
                  flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "webhook-source/1.0"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            print(f"[서비스] {fmt % args}", flush=True)

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        if self.path == "/subscriptions":
            with LOCK:
                self._send(200, {"subscribers": list(SUBSCRIBERS)})
        elif self.path == "/sensors/living-room":
            self._send(200, get())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/subscriptions":
            self._send(404, {"error": "not found"})
            return
        payload = self._read_json()
        if not payload or "callback" not in payload:
            self._send(400, {"error": "callback URL이 있어야 한다"})
            return
        with LOCK:
            if payload["callback"] not in SUBSCRIBERS:
                SUBSCRIBERS.append(payload["callback"])
        print(f"[서비스] 등록됨: {payload['callback']} (모두 {len(SUBSCRIBERS)}곳)", flush=True)
        self._send(201, {"subscribed": payload["callback"], "count": len(SUBSCRIBERS)})

    def do_PUT(self):
        if self.path != "/sensors/living-room":
            self._send(404, {"error": "not found"})
            return
        payload = self._read_json()
        try:
            record = set_value(float(payload["temperature"]))
        except (KeyError, TypeError, ValueError):
            self._send(400, {"error": "temperature 값이 있어야 한다"})
            return
        print(f"[서비스] 값이 바뀌었다: {record['temperature']}C — 등록된 곳을 부른다", flush=True)
        # 알림은 따로 돌린다. 부르는 데 걸리는 시간이 이 응답을 붙들면 안 된다.
        threading.Thread(target=notify_all, args=(record, self.server.verbose),
                         daemon=True).start()
        self._send(200, record)


def main():
    ap = argparse.ArgumentParser(description="Webhook을 보내는 센서 서비스")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9600)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.verbose = not args.quiet
    print(f"[서비스] http://{args.host}:{args.port}", flush=True)
    print("[서비스] POST /subscriptions 로 등록하고, PUT /sensors/living-room 로 값을 바꾼다",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[서비스] 멈춘다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
