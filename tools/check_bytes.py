#!/usr/bin/env python3
"""루트 readme 의 바이트 표를 실제로 돌려 맞댄다.

교재는 "실제로 돌려 재어 본 값이다" 라고 적어 두었다. 그 말이 참인지 이 스크립트가
확인한다. 서버를 띄우고 교재가 적어 둔 클라이언트로 재어, 루트 `readme.md` 의 표와
맞댄다. 표를 고치면 이 검사가 따라온다. 기대값을 스크립트 안에 적어 두지 않고
**표에서 읽어 오기** 때문이다.

    python3 tools/check_bytes.py
    python3 tools/check_bytes.py --port-base 31500      # 포트가 겹칠 때
    python3 tools/check_bytes.py --grpc-python ~/venv/bin/python

왜 최댓값을 맞대는가. 본문 길이는 `ts` 끝자리에 따라 한두 바이트 흔들리고 응답도
함께 흔들린다. 허용 범위로 맞대면 그 범위 안의 틀린 값이 통과한다. 그래서 서버를
다섯 번 새로 띄워 **최댓값**이 표의 값과 같은지 본다. 다섯 번으로 되는 까닭은 재어
보고 정했다 — 서른 번씩 재니 HTTP 본문은 74 가 96.7%, WebSocket 프레임은 76 이
90.0%, CoAP 응답은 83 이 86.7% 였다. CoAP 는 81·82·83 세 값으로 흔들린다. 가장
낮은 86.7% 로 셈해도 다섯 번에 최댓값이 한 번도 안 나올 확률이 0.133^5 = 0.00004 다.

**안 본 행이 있으면 통과로 세지 않는다.** gRPC 행은 `grpcio` 가 있어야 재는데, 없을 때
"전부 맞다" 로 끝내면 검사가 있다는 말만 남고 지키는 것은 없다.
"""
import argparse
import re
import socket
import subprocess
import sys
import time
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]   # tools/ 의 한 단계 위가 저장소 뿌리다
PY3 = sys.executable


def table():
    """루트 readme 의 바이트 표를 읽는다. 검사의 기대값은 여기서만 온다."""
    s = (REPO / "readme.md").read_text(encoding="utf-8")
    rows = {}
    for m in re.finditer(r"^\| (HTTP/1\.1|CoAP|MQTT PUBLISH|WebSocket 프레임|gRPC \(protobuf\)) \|"
                         r" ([^|]+)\| ([^|]+)\| ([^|]+)\| ([^|]+)\|", s, re.M):
        name, req, resp, body, proto = (x.strip() for x in m.groups())
        rows[name] = {"요청": req, "응답": resp, "본문": body, "규약": proto}
    if len(rows) != 5:
        raise RuntimeError(f"표에서 다섯 행을 못 읽었다 (읽은 것 {len(rows)}개)")
    hs = re.search(r"핸드셰이크 (\d+) 별도", rows["WebSocket 프레임"]["규약"])
    if not hs:
        raise RuntimeError("WebSocket 행에서 핸드셰이크 값을 못 읽었다")
    rows["WebSocket 프레임"]["핸드셰이크"] = hs.group(1)
    return rows


def free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def serve(rel, port):
    p = subprocess.Popen([PY3, str(REPO / rel), "--port", str(port)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        time.sleep(0.1)
        if not free(port):
            return p
    p.kill()
    raise RuntimeError(f"{rel} 가 포트 {port} 에서 안 떴다. 포트가 막혀 있는지 본다")


def run(rel, args):
    o = subprocess.run([PY3, str(REPO / rel), *args], capture_output=True,
                       text=True, timeout=60, cwd=REPO)
    return o.stdout + o.stderr


def num(pat, text, label):
    m = re.search(pat, text)
    if not m:
        raise RuntimeError(f"{label}: 출력에서 수치를 못 찾았다")
    return int(m.group(1))


class Check:
    """흔들리는 값을 범위로 보지 않는다. 여러 번 재어 최댓값을 표와 맞댄다.

    범위로 보면 그 범위 안의 틀린 값이 통과한다. 21회차에 그 틈이 일곱 개 있었다.

    다섯 번이면 되는 까닭은 재어 보고 정했다(22회차). 서른 번씩 재니 HTTP 본문은
    74 가 96.7%, WebSocket 프레임은 76 이 90.0%, CoAP 응답은 83 이 86.7% 다.
    **CoAP 는 두 값이 아니라 81·82·83 세 값으로 흔들린다.** 가장 낮은 86.7% 로 셈해도
    다섯 번에 최댓값이 한 번도 안 나올 확률이 0.133^5 = 0.00004 다. 그래서 다섯 번
    가운데 최댓값이 표의 값과 같아야 하고, 안 같으면 표가 틀렸다.
    """

    def __init__(self):
        self.bad = 0
        self.unseen = []

    def __call__(self, label, samples, want, why=""):
        want = int(want)
        got = max(samples)
        ok = got == want
        spread = "" if len(set(samples)) == 1 else f" (잰 값 {sorted(set(samples))})"
        print(f"  {'OK ' if ok else 'FAIL'} {label:<20} 최댓값 {got:<5} 표 {want:<5}{spread} {why}")
        if not ok:
            self.bad += 1

    def skip(self, label, why):
        print(f"  --   {label:<20} 안 본다 — {why}")
        self.unseen.append(label)


def main():
    ap = argparse.ArgumentParser(description="루트 readme 의 바이트 표를 돌려서 맞댄다")
    ap.add_argument("--port-base", type=int, default=21500,
                    help="띄울 서버의 첫 포트 (기본 21500). 다섯 개를 이어 쓴다")
    ap.add_argument("--ws-port", type=int, default=9876,
                    help="WebSocket 핸드셰이크를 잴 포트 (기본 9876). "
                         "표는 포트 8081(네 자리)에서 잰 값이라 자릿수를 맞춰야 284 가 나온다")
    ap.add_argument("--grpc-python", default=None,
                    help="grpcio 가 깔린 python. 안 주면 지금 python 으로 해 보고 없으면 건너뛴다")
    ap.add_argument("--runs", type=int, default=5, help="흔들리는 값을 몇 번 재나 (기본 5)")
    args = ap.parse_args()
    if len(str(args.ws_port)) != 4:
        print("--ws-port 는 네 자리여야 한다. 표의 284 가 포트 8081 에서 잰 값이다",
              file=sys.stderr)
        return 2
    BASE, WS_PORT, N = args.port_base, args.ws_port, args.runs
    try:
        t = table()
    except RuntimeError as exc:
        print(f"표를 읽지 못했다: {exc}", file=sys.stderr)
        return 2
    print("루트 readme 의 표에서 기대값을 읽어 와 돌려서 맞댄다")
    print("흔들리는 값은 서버를 여러 번 새로 띄워 최댓값을 맞댄다\n")
    ck = Check()

    # HTTP — 서버를 N번 새로 띄워야 ts 가 바뀐다. 한 서버에 여러 번 물으면 값이 그대로다.
    req, body, resp = [], [], []
    for k in range(N):
        srv = serve("04-application/http/minimal_server.py", BASE)
        try:
            o = run("04-application/http/raw_client.py",
                    ["127.0.0.1", "/sensors/living-room/temperature", "--port", str(BASE)])
            req.append(num(r"요청 (\d+)바이트", o, "HTTP 요청"))
            body.append(num(r"본문 (\d+)", o, "HTTP 본문"))
            resp.append(num(r"응답 전체 (\d+)바이트", o, "HTTP 응답"))
        finally:
            srv.kill()
            time.sleep(0.2)
    ck("HTTP 요청", req, t["HTTP/1.1"]["요청"])
    ck("HTTP 본문", body, t["HTTP/1.1"]["본문"], "ts 로 흔들린다")
    ck("HTTP 응답", resp, t["HTTP/1.1"]["응답"], "본문과 함께 흔들린다")

    # WebSocket — 핸드셰이크는 표와 같은 네 자리 포트에서 재야 값이 맞는다
    hs, frame = [], []
    for k in range(N):
        srv = serve("04-application/websocket/server.py", WS_PORT)
        try:
            o = run("04-application/websocket/raw_client.py", ["--port", str(WS_PORT)])
            hs.append(num(r"핸드셰이크 요청 (\d+)바이트", o, "WS 요청")
                      + num(r"응답 (\d+)바이트", o, "WS 응답"))
            frame.append(num(r"프레임 (\d+)바이트", o, "WS 프레임"))
        finally:
            srv.kill()
            time.sleep(0.2)
    ck("WS 핸드셰이크", hs, t["WebSocket 프레임"]["핸드셰이크"], f"포트 {WS_PORT}(네 자리)")
    ck("WS 프레임", frame, t["WebSocket 프레임"]["응답"], "본문과 함께 흔들린다")

    # MQTT — 본문이 온도 글자만이라 흔들리지 않는다. 한 번으로 넉넉하다.
    srv = serve("04-application/mqtt/broker.py", BASE + 2)
    try:
        o = run("04-application/mqtt/publisher.py", ["--port", str(BASE + 2)])
        ck("MQTT PUBLISH", [num(r"PUBLISH\s+(\d+)바이트", o, "MQTT")], t["MQTT PUBLISH"]["응답"])
    finally:
        srv.kill()

    # CoAP — 교재의 client.py 를 그대로 쓴다. 손으로 패킷을 만들면 교재와 다르게 잰다.
    # 처음에 토큰을 1바이트로 만들어 37 이 나왔는데 client.py 는 2바이트를 쓴다(38).
    # 검사는 교재가 적어 둔 명령으로 재야 한다.
    creq, cresp = [], []
    for k in range(N):
        srv = subprocess.Popen([PY3, str(REPO / "04-application/coap/server.py"),
                                "--port", str(BASE + 3)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.2)
        try:
            o = run("04-application/coap/client.py", ["get", "--port", str(BASE + 3)])
            creq.append(num(r"보내는 메시지 (\d+)바이트", o, "CoAP 요청"))
            cresp.append(num(r"답 (\d+)바이트", o, "CoAP 응답"))
        finally:
            srv.kill()
            time.sleep(0.2)
    ck("CoAP 요청", creq, t["CoAP"]["요청"])
    ck("CoAP 응답", cresp, t["CoAP"]["응답"], "본문과 함께 흔들린다")

    # gRPC — grpcio 가 있어야 한다. 없으면 안 본다고 적고 통과로 세지 않는다.
    gpy = args.grpc_python or PY3
    has_grpc = subprocess.run([gpy, "-c", "import grpc"],
                              capture_output=True).returncode == 0
    if has_grpc:
        srv = subprocess.Popen([gpy, str(REPO / "05-api-layers/05-grpc-api/server.py"),
                                "--port", str(BASE + 4)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(4)
        try:
            o = subprocess.run([gpy, "client.py", "size", "--port", str(BASE + 4)],
                               capture_output=True, text=True, timeout=60,
                               cwd=REPO / "05-api-layers/05-grpc-api").stdout
            ck("gRPC protobuf", [num(r"protobuf\s+(\d+)바이트", o, "gRPC")],
               t["gRPC (protobuf)"]["본문"])
        finally:
            srv.kill()
    else:
        ck.skip("gRPC protobuf", f"{gpy} 에 grpcio 가 없다. --grpc-python 으로 알려 준다")

    print()
    if ck.bad:
        print(f"어긋난 곳 {ck.bad}건")
        return 1
    # 안 본 행이 있으면 "맞다" 고 하지 않는다. 22회차에 그 틈이 드러났다 —
    # gRPC 를 못 볼 때 "전부 맞다" 를 찍고 끝난 코드 0 으로 끝났다. 표에 다섯 행이
    # 있는데 넷만 보고 통과하면, 검사가 있다는 말만 남고 지키는 것은 없다.
    if ck.unseen:
        print(f"다 못 봤다 — 안 본 행 {len(ck.unseen)}개: {', '.join(ck.unseen)}")
        print("  본 행은 다 맞았다. 그래도 통과로 세지 않는다.")
        return 1
    print("전부 맞다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
