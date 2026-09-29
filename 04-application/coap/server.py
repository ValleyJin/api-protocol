#!/usr/bin/env python3
"""CoAP 서버. 공통 과제(센서 값 올리고 읽기)를 CoAP로 구현한다.

외부 패키지를 쓰지 않는다. UDP 소켓 하나와 coap.py만으로 돈다.

    GET  /sensors/living-room/temperature   값을 읽는다
    PUT  /sensors/living-room/temperature   값을 올린다

--drop-ack 옵션을 켜면 ACK를 일부러 보내지 않는다. 클라이언트가 CON 메시지를
몇 번 다시 보내는지 눈으로 확인하려고 만들었다. 서버를 그냥 내리면 커널이
ICMP port unreachable을 돌려주어 클라이언트가 재전송을 포기한다. 그래서
재전송을 보려면 서버는 살아 있되 답을 안 하는 쪽이 맞다.

    python3 server.py
    python3 server.py --drop-ack       # 재전송을 보려면 이쪽
"""

import argparse
import pathlib
import socket
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import coap  # noqa: E402
from common.sensor import PATH, encode_json, reading  # noqa: E402

STATE = {"latest": reading(21.0)}


def handle(data, addr, sock, drop_ack, verbose):
    try:
        msg = coap.decode(data)
    except ValueError as exc:
        print(f"[서버] 읽지 못한 메시지: {exc}")
        return

    path = coap.path_of(msg["options"])
    if verbose:
        print(f"[서버] {addr[0]}:{addr[1]} {msg['type_name']} {msg['code_name']} "
              f"MID={msg['mid']} 경로={path} 전체 {msg['size']}바이트")

    if drop_ack and msg["type"] == coap.TYPE_CON:
        print(f"[서버] ACK를 일부러 보내지 않는다 (MID={msg['mid']}). "
              "클라이언트가 다시 보내는지 본다.")
        return

    # 응답 종류를 정한다. CON으로 왔으면 ACK에 답을 실어 보낸다(piggyback).
    # NON으로 왔으면 NON으로 답한다. 이 짝을 맞추는 것도 우리 몫이다.
    reply_type = coap.TYPE_ACK if msg["type"] == coap.TYPE_CON else coap.TYPE_NON

    if path != PATH:
        reply = coap.encode(reply_type, coap.CODE_NOT_FOUND, msg["mid"], msg["token"])
    elif msg["code"] == coap.CODE_GET:
        body = encode_json(STATE["latest"])
        reply = coap.encode(reply_type, coap.CODE_CONTENT, msg["mid"], msg["token"],
                            [(coap.OPT_CONTENT_FORMAT, coap.CONTENT_JSON)], body)
    elif msg["code"] == coap.CODE_PUT:
        try:
            value = float(msg["payload"].decode().strip() or 0)
        except ValueError:
            reply = coap.encode(reply_type, coap.CODE_BAD_REQUEST, msg["mid"], msg["token"])
        else:
            STATE["latest"] = reading(value)
            print(f"[서버] 값을 올렸다: {value}C")
            reply = coap.encode(reply_type, coap.CODE_CHANGED, msg["mid"], msg["token"])
    else:
        reply = coap.encode(reply_type, coap.CODE_METHOD_NOT_ALLOWED, msg["mid"], msg["token"])

    sock.sendto(reply, addr)
    if verbose:
        print(f"[서버] 답 {len(reply)}바이트를 보냈다.")


def main():
    ap = argparse.ArgumentParser(description="CoAP 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5683)   # CoAP가 쓰는 표준 포트
    ap.add_argument("--drop-ack", action="store_true", help="ACK를 보내지 않는다")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    print(f"[서버] coap://{args.host}:{args.port}{PATH}")
    if args.drop_ack:
        print("[서버] ACK를 보내지 않는 모드다.")
    print("[서버] 멈추려면 Ctrl+C")

    try:
        while True:
            data, addr = sock.recvfrom(65535)
            handle(data, addr, sock, args.drop_ack, not args.quiet)
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
