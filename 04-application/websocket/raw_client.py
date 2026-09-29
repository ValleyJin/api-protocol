#!/usr/bin/env python3
"""WebSocket 클라이언트. 핸드셰이크와 프레임을 손으로 만든다.

라이브러리를 쓰지 않는다. 소켓 하나로 HTTP 요청을 보내고, 101을 받은 뒤부터
같은 연결에 프레임을 흘려보낸다. '연결을 끊지 않고 주고받는다'가 코드에서
어떻게 생겼는지 여기서 드러난다.

    python3 raw_client.py
    python3 raw_client.py --send '{"set":24.0}'
    python3 raw_client.py --count 3
"""

import argparse
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ws  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="직접 만든 WebSocket 클라이언트")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--path", default="/ws")
    ap.add_argument("--send", help="붙은 뒤 이 텍스트를 한 번 보낸다")
    ap.add_argument("--count", type=int, default=3, help="이만큼 받으면 끝낸다")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as exc:
        print(f"붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
        return 1

    # ── 1단계: 평범한 HTTP 요청 ──────────────────────────────────────
    key = ws.new_key()
    request = (
        f"GET {args.path} HTTP/1.1\r\n"
        f"Host: {args.host}:{args.port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode()
    sock.sendall(request)
    print(f"핸드셰이크 요청 {len(request)}바이트 보냄 (이 부분은 아직 HTTP다)")
    print(f"  Sec-WebSocket-Key: {key}")

    raw = b""
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(4096)
        if not chunk:
            print("서버가 답 없이 끊었다.", file=sys.stderr)
            return 1
        raw += chunk
    sep = raw.find(b"\r\n\r\n") + 4
    head, buffer = raw[:sep], raw[sep:]

    status_line, headers = ws.parse_http_headers(head)
    print(f"\n응답 {len(head)}바이트")
    print(f"  {status_line}")
    if "101" not in status_line:
        print("101이 아니다. 서버가 WebSocket으로 바꿔 주지 않았다.", file=sys.stderr)
        return 1

    expected = ws.accept_key(key)
    got = headers.get("sec-websocket-accept")
    print(f"  Sec-WebSocket-Accept: {got}")
    print(f"  내가 구한 값과 같은가: {got == expected}")
    print("  같지 않으면 연결을 끊어야 한다. 중간에서 흉내 낸 응답일 수 있다.")
    print("\n여기서부터 HTTP가 아니다. 같은 TCP 연결 위에 프레임이 흐른다.\n")

    # ── 2단계: 프레임 주고받기 ───────────────────────────────────────
    if args.send:
        frame = ws.encode_frame(args.send, mask=True)   # 클라이언트는 반드시 마스킹한다
        sock.sendall(frame)
        print(f"보냄: {args.send!r} → 프레임 {len(frame)}바이트 "
              f"(헤더 2 + 마스크키 4 + 본문 {len(args.send.encode())})")
        print("  마스크키 4바이트가 그냥 붙는다. 짧은 메시지일수록 비율이 크다.\n")

    received, started = 0, time.time()
    try:
        while received < args.count and time.time() - started < args.timeout:
            sock.settimeout(1.0)
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buffer += chunk
            while True:
                frame, buffer = ws.decode_frame(buffer)
                if frame is None:
                    break
                if frame["opcode"] == ws.OP_CLOSE:
                    print("서버가 닫기 프레임을 보냈다.")
                    received = args.count
                    break
                if frame["opcode"] != ws.OP_TEXT:
                    continue
                received += 1
                body = frame["payload"].decode(errors="replace")
                print(f"[{received}] 서버가 밀어 준 값: {body}")
                print(f"      프레임 {frame['size']}바이트 = 헤더 {frame['header_size']} "
                      f"+ 본문 {len(frame['payload'])}   마스킹됨={frame['masked']}")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sock.sendall(ws.encode_frame(b"", ws.OP_CLOSE, mask=True))
        except OSError:
            pass
        sock.close()

    print()
    print("짚을 것")
    print("  핸드셰이크 한 번에 수백 바이트를 쓰지만 그 뒤로는 프레임 헤더가 2바이트다.")
    print("  HTTP로 같은 값을 열 번 받으면 요청 120 + 응답 199 를 열 번 되풀이한다.")
    print("  값이 자주 바뀌고 오래 이어질수록 WebSocket이 유리하다.")
    print("  대신 연결을 계속 붙들고 있어야 한다. 서버가 동시 연결 수만큼 자원을 쓴다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
