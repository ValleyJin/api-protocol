#!/usr/bin/env python3
"""여덟 가지 API 방식을 한 번에 돌려 견준다.

서버를 차례로 띄우고, 같은 일(센서 값 한 건 읽기)을 각 방식으로 시킨 뒤
같은 잣대로 잰다. 이 폴더의 결론을 한 화면에 모으는 파일이다.

재는 것
    코드 줄 수   서버와 클라이언트 파일의 빈 줄과 주석을 뺀 줄 수
    왕복 시간    한 번 부르는 데 걸린 시간
    본문 크기    애플리케이션이 실제로 주고받은 바이트

여기서 재지 못하는 것도 밝혀 둔다. 실제로 오가는 전체 바이트는 캡처를 떠야
정확히 센다. TCP 헤더, IP 헤더, TLS까지 세려면 06-encapsulation 으로 간다.

    python3 compare.py
    python3 compare.py --skip-grpc
"""

import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent


def count_lines(*paths):
    """빈 줄과 주석을 뺀 줄 수를 센다. docstring은 세지 않는다."""
    total = 0
    for path in paths:
        full = ROOT / path
        if not full.exists():
            continue
        in_doc, quote = False, None
        for line in full.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if in_doc:
                if quote in stripped:
                    in_doc = False
                continue
            if stripped.startswith(('"""', "'''")):
                quote = stripped[:3]
                if not (len(stripped) > 3 and stripped.endswith(quote)):
                    in_doc = True
                continue
            if not stripped or stripped.startswith("#"):
                continue
            total += 1
    return total


class Server:
    """서버를 띄우고 준비될 때까지 기다렸다가, 끝나면 내린다."""

    def __init__(self, script, port, extra=None):
        self.script = ROOT / script
        self.port = port
        self.extra = extra or []
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(self.script), "--port", str(self.port), "-q"] + self.extra,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(self.script.parent))
        # 포트가 열릴 때까지 기다린다
        import socket
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.2):
                    time.sleep(0.3)
                    return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"{self.script.name} 이 {self.port} 포트를 열지 않았다")

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return False


def measure(fn, warmup=1, runs=3):
    """warmup 뒤 runs번 돌려 가장 빠른 시간을 쓴다."""
    for _ in range(warmup):
        fn()
    best, payload = None, 0
    for _ in range(runs):
        started = time.time()
        payload = fn()
        elapsed = (time.time() - started) * 1000
        best = elapsed if best is None else min(best, elapsed)
    return best, payload


# ── 방식별 측정 ───────────────────────────────────────────────────────
def probe_socket(port):
    import socket
    with socket.create_connection(("127.0.0.1", port), 3) as sock:
        def once():
            sock.sendall(b"GET\n")
            reply = b""
            while not reply.endswith(b"\n"):
                reply += sock.recv(256)
            return len(reply)
        return measure(once)


def probe_rest(port):
    def once():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/sensors/living-room", timeout=3) as r:
            return len(r.read())
    return measure(once)


def probe_graphql(port):
    body = json.dumps({"query": '{ sensor(id:"living-room") { temperature } }'}).encode()
    def once():
        request = urllib.request.Request(f"http://127.0.0.1:{port}/graphql", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as r:
            return len(r.read())
    return measure(once)


def probe_grpc(port):
    sys.path.insert(0, str(ROOT / "05-grpc-api"))
    import grpc
    import sensor_pb2
    import sensor_pb2_grpc
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = sensor_pb2_grpc.SensorServiceStub(channel)
    request = sensor_pb2.SensorId(id="living-room")
    def once():
        return len(stub.Get(request, timeout=3).SerializeToString())
    try:
        return measure(once)
    finally:
        channel.close()


def probe_websocket(port):
    sys.path.insert(0, str(ROOT / "06-websocket-api"))
    from client import Client
    client = Client("127.0.0.1", port)
    def once():
        message, sent, got = client.call("get")
        return got
    try:
        return measure(once)
    finally:
        client.close()


def probe_sdk(port):
    sys.path.insert(0, str(ROOT / "08-sdk-wrapper"))
    from sensor_sdk import SensorClient
    client = SensorClient(f"http://127.0.0.1:{port}")
    def once():
        client.get()
        # SDK는 REST 서버를 그대로 부르므로 본문 크기가 REST와 같아야 한다.
        # 짐작하지 않고 실제로 한 번 더 받아 세어 둔다.
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/sensors/living-room", timeout=3) as r:
            return len(r.read())
    return measure(once)


def main():
    ap = argparse.ArgumentParser(description="여덟 가지 API 방식을 견준다")
    ap.add_argument("--skip-grpc", action="store_true")
    args = ap.parse_args()

    rows = []

    print("서버를 차례로 띄우며 잰다. 몇 초 걸린다.\n")

    with Server("01-socket-api/server.py", 19100):
        ms, size = probe_socket(19100)
        rows.append(("소켓 API", count_lines("01-socket-api/server.py", "01-socket-api/client.py"),
                     ms, size, "내 규약, 내가 전부 적는다"))

    with Server("03-rest-api/server.py", 19200) as rest:
        ms, size = probe_rest(19200)
        rows.append(("REST", count_lines("03-rest-api/server.py", "03-rest-api/client.py"),
                     ms, size, "HTTP 메서드와 상태 코드를 쓴다"))

        ms, size = probe_sdk(19200)
        rows.append(("SDK", count_lines("08-sdk-wrapper/sensor_sdk.py", "08-sdk-wrapper/demo.py"),
                     ms, size, "REST 위에 재시도와 타입을 얹었다"))

    with Server("04-graphql-api/server.py", 19300):
        ms, size = probe_graphql(19300)
        rows.append(("GraphQL", count_lines("04-graphql-api/server.py", "04-graphql-api/client.py"),
                     ms, size, "받을 필드를 클라이언트가 고른다"))

    if not args.skip_grpc:
        try:
            with Server("05-grpc-api/server.py", 19400):
                ms, size = probe_grpc(19400)
                rows.append(("gRPC", count_lines("05-grpc-api/server.py", "05-grpc-api/client.py"),
                             ms, size, ".proto가 계약이다. protobuf로 싣는다"))
        except Exception as exc:
            print(f"gRPC는 건너뛴다: {exc}\n")

    with Server("06-websocket-api/server.py", 19500):
        ms, size = probe_websocket(19500)
        rows.append(("WebSocket API",
                     count_lines("06-websocket-api/server.py", "06-websocket-api/client.py"),
                     ms, size, "한 연결로 요청과 구독을 함께"))

    print("=" * 88)
    print(f"{'방식':<16}{'코드 줄':>8}{'왕복 ms':>10}{'본문 바이트':>13}   성격")
    print("=" * 88)
    for name, lines, ms, size, note in rows:
        print(f"{name:<16}{lines:>8}{ms:>10.2f}{size:>13}   {note}")
    print("=" * 88)
    print()
    print("Webhook은 이 표에 없다. '클라이언트가 부른다'는 잣대 자체가 맞지 않기 때문이다.")
    print("서버가 클라이언트를 부르므로 왕복 시간을 같은 뜻으로 잴 수 없다.")
    print("07-webhook 폴더에서 따로 확인한다.")
    print()
    print("읽는 법")
    print("  코드 줄이 적다고 좋은 것이 아니다. gRPC는 .proto와 생성 코드가 따로 있다.")
    print("  왕복 시간은 모두 루프백이라 실제 망에서는 순서가 달라질 수 있다.")
    print("  본문 바이트는 애플리케이션이 본 크기다. 실제로 오가는 전체 바이트는 06-encapsulation 이 센다.")
    print()
    print("고르는 기준")
    print("  기기가 좁은 망에 있다              → CoAP, MQTT (04-application)")
    print("  웹 브라우저가 부른다, 캐시가 필요하다 → REST")
    print("  화면마다 필요한 필드가 다르다        → GraphQL")
    print("  서비스끼리 부른다, 속도가 중요하다    → gRPC")
    print("  값이 자주 바뀌고 바로 알아야 한다     → WebSocket")
    print("  상대가 내 서버를 부르게 하고 싶다     → Webhook")
    print("  남에게 내 API를 쓰게 한다            → SDK를 함께 낸다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
