#!/usr/bin/env python3
"""WebSocket API 클라이언트. 한 연결로 요청도 하고 구독도 한다.

REST 클라이언트와 견줘 보면 내가 더 해야 하는 일이 보인다.

    요청마다 id를 붙이고 답을 그 id로 짝지어야 한다
    서버가 먼저 보내는 event를 요청의 답과 갈라 읽어야 한다
    연결이 끊기면 다시 붙어야 한다 (여기서는 다루지 않는다)

그 대신 얻는 것도 분명하다. 값이 바뀌는 순간 바로 안다. REST로 같은 일을
하려면 계속 물어봐야 한다(폴링).

    python3 client.py get
    python3 client.py set 24.5
    python3 client.py watch
    python3 client.py poll-compare     # 폴링과 구독의 요청 수를 견준다
"""

import argparse
import json
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "04-application" / "websocket"))
import ws  # noqa: E402


class Client:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), 5)
        self.buffer = b""
        self.next_id = 1
        self.sent_bytes = self.recv_bytes = 0

        key = ws.new_key()
        request = (f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n").encode()
        self.sock.sendall(request)
        self.sent_bytes += len(request)

        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += self.sock.recv(4096)
        self.recv_bytes += len(raw)
        sep = raw.find(b"\r\n\r\n") + 4
        status, headers = ws.parse_http_headers(raw[:sep])
        if "101" not in status or headers.get("sec-websocket-accept") != ws.accept_key(key):
            raise ConnectionError("핸드셰이크에 실패했다")
        self.buffer = raw[sep:]
        self.handshake_bytes = len(request) + sep

    def send(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        frame = ws.encode_frame(body, mask=True)
        self.sock.sendall(frame)
        self.sent_bytes += len(frame)
        return len(frame)

    def recv(self, timeout=5.0):
        deadline = time.time() + timeout
        while True:
            frame, self.buffer = ws.decode_frame(self.buffer)
            if frame is not None:
                if frame["opcode"] != ws.OP_TEXT:
                    continue
                return json.loads(frame["payload"]), frame["size"]
            remaining = deadline - time.time()
            if remaining <= 0:
                return None, 0
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None, 0
            if not chunk:
                raise ConnectionError("서버가 끊었다")
            self.buffer += chunk
            self.recv_bytes += len(chunk)

    def call(self, method, params=None):
        """요청 하나를 보내고 그 id에 맞는 답을 기다린다.

        답이 오기 전에 event가 끼어들 수 있다. id로 갈라야 하는 까닭이다.
        """
        rid = self.next_id
        self.next_id += 1
        sent = self.send({"id": rid, "method": method, **({"params": params} if params else {})})
        while True:
            message, size = self.recv()
            if message is None:
                return None, sent, 0
            if message.get("id") == rid:
                return message, sent, size
            # id가 없는 것은 서버가 먼저 보낸 event다. 여기서는 흘려보낸다.

    def close(self):
        try:
            self.sock.sendall(ws.encode_frame(b"", ws.OP_CLOSE, mask=True))
        except OSError:
            pass
        self.sock.close()


def main():
    ap = argparse.ArgumentParser(description="WebSocket API 클라이언트")
    ap.add_argument("command", choices=["get", "set", "watch", "poll-compare"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9500)
    ap.add_argument("--count", type=int, default=3)
    args = ap.parse_args()

    try:
        client = Client(args.host, args.port)
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
        return 1

    print(f"핸드셰이크에 {client.handshake_bytes}바이트를 썼다. 이 값은 연결마다 한 번이다.\n")

    try:
        if args.command == "get":
            message, sent, got = client.call("get")
            print(f"get() → {message['result']['temperature']}"
                  f"{message['result']['unit']}")
            print(f"  요청 프레임 {sent}바이트, 응답 프레임 {got}바이트")
            print(f"  REST의 GET은 요청 78 + 응답 243 정도였다. 프레임이 훨씬 짧다.")
            print(f"  대신 핸드셰이크 {client.handshake_bytes}바이트를 미리 냈다.")
            print(f"  요청 {client.handshake_bytes // (sent + got)}번쯤부터 이득이 난다.")

        elif args.command == "set":
            if args.value is None:
                print("set에는 값이 필요하다.", file=sys.stderr)
                return 1
            message, sent, got = client.call("set", {"temperature": float(args.value)})
            print(f"set({args.value}) → {message.get('result', message.get('error'))}")

        elif args.command == "watch":
            message, _, _ = client.call("subscribe")
            print(f"subscribe → {message['result']}")
            print(f"{args.count}건을 기다린다. 다른 창에서 set을 돌려 본다.\n")
            received = 0
            while received < args.count:
                event, size = client.recv(timeout=30)
                if event is None:
                    print("시간이 다 됐다.")
                    break
                if event.get("event") != "reading":
                    continue
                received += 1
                print(f"[{received}] {event['data']['temperature']}"
                      f"{event['data']['unit']}  (프레임 {size}바이트)")
            print("\n요청은 subscribe 한 번뿐이었다. 나머지는 서버가 먼저 보냈다.")

        else:  # poll-compare
            print("같은 시간 동안 폴링과 구독이 각각 몇 번 오가는지 센다.\n")
            seconds = 3

            # 폴링: 0.3초마다 물어본다
            polls, before = 0, client.sent_bytes + client.recv_bytes
            started = time.time()
            while time.time() - started < seconds:
                client.call("get")
                polls += 1
                time.sleep(0.3)
            poll_bytes = client.sent_bytes + client.recv_bytes - before

            # 구독: 한 번 걸어 두고 받기만 한다
            client.call("subscribe")
            before, events = client.sent_bytes + client.recv_bytes, 0
            started = time.time()
            while time.time() - started < seconds:
                event, _ = client.recv(timeout=0.5)
                if event and event.get("event") == "reading":
                    events += 1
            sub_bytes = client.sent_bytes + client.recv_bytes - before

            print(f"  폴링 {seconds}초: 요청 {polls}번, 오간 바이트 {poll_bytes}")
            print(f"  구독 {seconds}초: 받은 event {events}건, 오간 바이트 {sub_bytes}")
            print()
            print("  폴링은 값이 안 바뀌어도 계속 묻는다. 그 요청이 모두 헛수고다.")
            print("  구독은 바뀔 때만 온다. 대신 연결을 계속 붙들고 있어야 한다.")
            print("  값이 자주 바뀌지 않고 클라이언트가 아주 많으면 폴링이 나을 때도 있다.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
