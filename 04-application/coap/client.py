#!/usr/bin/env python3
"""CoAP 클라이언트. CON의 재전송까지 직접 구현한다.

TCP가 없으니 "답이 안 오면 다시 보낸다"를 애플리케이션이 해야 한다. RFC 7252는
첫 대기 2초에서 시작해 갑절씩 늘리며 최대 4번 다시 보내라고 정한다. 아래
send_confirmable()이 그것이다. 03 폴더에서 TCP가 대신 해 주던 일을, 여기서는
여기서는 직접 적는다.

    python3 client.py get
    python3 client.py put 23.5
    python3 client.py get --non         # 재전송 없는 NON으로 보낸다
    python3 client.py get --compare     # 같은 값을 HTTP로 받을 때와 견준다
"""

import argparse
import pathlib
import random
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import coap  # noqa: E402
from common.sensor import PATH  # noqa: E402


def send_confirmable(sock, addr, packet, mid, verbose=True):
    """CON 메시지를 보내고 ACK가 올 때까지 갑절씩 늘려 가며 다시 보낸다."""
    timeout = coap.ACK_TIMEOUT
    for attempt in range(coap.MAX_RETRANSMIT + 1):
        sock.sendto(packet, addr)
        label = "처음 보냄" if attempt == 0 else f"{attempt}번째 재전송"
        if verbose:
            print(f"  [{label}] {len(packet)}바이트, {timeout:.0f}초 기다린다")
        sock.settimeout(timeout)
        try:
            data, _ = sock.recvfrom(65535)
            return data
        except socket.timeout:
            timeout *= 2    # 갑절로 늘린다(exponential backoff)
    return None


def send_non(sock, addr, packet, verbose=True):
    """NON 메시지는 한 번 보내고 만다. 답이 없어도 다시 보내지 않는다."""
    sock.sendto(packet, addr)
    if verbose:
        print(f"  [한 번만 보냄] {len(packet)}바이트 — NON은 재전송하지 않는다")
    sock.settimeout(coap.ACK_TIMEOUT)
    try:
        data, _ = sock.recvfrom(65535)
        return data
    except socket.timeout:
        return None


def main():
    ap = argparse.ArgumentParser(description="CoAP 클라이언트")
    ap.add_argument("method", choices=["get", "put"])
    ap.add_argument("value", nargs="?", help="put일 때 올릴 온도")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5683)
    ap.add_argument("--path", default=PATH)
    ap.add_argument("--non", action="store_true", help="CON 대신 NON으로 보낸다")
    ap.add_argument("--compare", action="store_true", help="HTTP와 바이트 수를 견준다")
    args = ap.parse_args()

    mid = random.randint(0, 0xFFFF)
    token = random.randbytes(2)
    options = coap.path_options(args.path)
    payload = b""
    if args.method == "put":
        if args.value is None:
            print("put에는 올릴 값이 필요하다. 예: python3 client.py put 23.5", file=sys.stderr)
            return 1
        payload = args.value.encode()
        options.append((coap.OPT_CONTENT_FORMAT, coap.CONTENT_TEXT))

    code = coap.CODE_GET if args.method == "get" else coap.CODE_PUT
    msg_type = coap.TYPE_NON if args.non else coap.TYPE_CON
    packet = coap.encode(msg_type, code, mid, token, options, payload)

    print(f"보내는 메시지 {len(packet)}바이트 ({coap.TYPE_NAMES[msg_type]} {coap.code_name(code)})")
    print("  " + " ".join(f"{b:02x}" for b in packet))
    print(f"  헤더 4 + 토큰 {len(token)} + 옵션 "
          f"{len(packet) - 4 - len(token) - (len(payload) + 1 if payload else 0)}"
          f" + 본문 {len(payload)}")
    print()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (args.host, args.port)
    started = time.time()
    data = send_non(sock, addr, packet) if args.non else send_confirmable(sock, addr, packet, mid)
    elapsed = (time.time() - started) * 1000
    sock.close()

    if data is None:
        print()
        if args.non:
            print("답이 없다. NON은 여기서 끝이다. 잃어버려도 아무도 모른다.")
        else:
            print(f"{coap.MAX_RETRANSMIT}번 다시 보냈지만 답이 없다. 포기한다.")
            print("서버가 --drop-ack 로 떠 있거나 아예 없으면 이것이 정상이다.")
            print("이 소켓은 connect() 하지 않아 ICMP port unreachable을 받지 않는다.")
            print("그래서 서버가 없어도 끝까지 다시 보낸다.")
        return 1

    reply = coap.decode(data)
    print()
    print(f"답 {reply['size']}바이트: {reply['type_name']} {reply['code_name']} "
          f"MID={reply['mid']} ({elapsed:.1f}ms)")
    print(f"  토큰이 맞는가: {reply['token'] == token}")
    if reply["payload"]:
        print(f"  본문 {len(reply['payload'])}바이트: {reply['payload'].decode(errors='replace')}")

    if args.compare:
        print()
        print("=" * 62)
        print("같은 값을 받는 데 든 바이트")
        print("=" * 62)
        body = len(reply["payload"])
        print(f"  CoAP 요청 {len(packet):>4}바이트   응답 {reply['size']:>4}바이트  "
              f"(본문 {body})")
        if args.path == PATH:
            print(f"  HTTP 요청  120바이트   응답  199바이트  (본문 74)")
            print("  * HTTP 수치는 04-application/http/raw_client.py 를 같은 값으로 돌렸을 때다.")
            print()
            print(f"  CoAP가 규약에 쓴 바이트: {len(packet) + reply['size'] - body}")
            print(f"  HTTP가 규약에 쓴 바이트: {120 + 199 - 74}")
            print("  좁은 망에서 배터리로 도는 기기에는 이 차이가 크다.")
        else:
            print(f"  CoAP가 규약에 쓴 바이트: {len(packet) + reply['size'] - body}")
            print()
            print("  HTTP 쪽은 찍지 않는다. 적어 둔 HTTP 수치는 기본 경로로 잰 것이라")
            print(f"  --path 를 {args.path} 로 바꾼 지금과는 견줄 수 없다. HTTP 요청도")
            print("  경로를 그대로 싣기 때문에 경로를 줄이면 HTTP도 함께 줄어든다.")
            print(f"  견주려면 --path 를 {PATH} 로 두고 다시 돌린다.")
        print("  대신 CoAP는 UDP라 재전송과 순서를 스스로 챙겨야 한다. 위에서 본 대로다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
