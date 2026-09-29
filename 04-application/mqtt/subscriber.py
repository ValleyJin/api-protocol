#!/usr/bin/env python3
"""MQTT 구독자. 주제를 걸어 두고 값이 오기를 기다린다.

retain과 clean session을 눈으로 확인하는 것이 이 파일의 목적이다.

  retain 실습
    1) python3 broker.py
    2) python3 publisher.py 23.5 --retain        (구독자가 없는 채로 올린다)
    3) python3 subscriber.py                     (붙자마자 23.5가 온다)
    --retain 없이 2)를 하면 3)에서 아무것도 안 온다. 그 차이가 retain이다.

  clean session 실습
    1) python3 subscriber.py --persist --qos 1   (client id 고정, clean=False)
    2) Ctrl+C로 끈다
    3) python3 publisher.py 24.0 --qos 1         (끊겨 있는 동안 올린다)
    4) python3 subscriber.py --persist --qos 1   (다시 붙으면 24.0이 몰려 온다)
    --persist 없이 하거나 --qos 0 이면 3)의 값은 사라진다. 조건 세 개가 모두 필요하다.
    발행자도 QoS 1 이상이어야 한다. QoS 0 메시지는 브로커가 쌓지 않는다.

여기서 한 가지 함정이 드러난다. 세션을 되살리면 브로커가 CONNACK 바로 뒤에
쌓아 둔 PUBLISH를 몰아 보낸다. 그래서 SUBACK보다 PUBLISH가 먼저 도착할 수 있다.
"보낸 순서대로 답이 온다"고 여기고 짜면 여기서 깨진다. 아래 next_packet()처럼
종류를 보고 갈라 처리해야 한다.

    python3 subscriber.py
    python3 subscriber.py --persist --qos 1 --count 3
"""

import argparse
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mqtt  # noqa: E402
from common.sensor import TOPIC  # noqa: E402


class Connection:
    """받은 바이트를 모아 두었다가 패킷 하나씩 꺼내 준다.

    TCP는 메시지 경계를 지켜 주지 않는다(03 폴더에서 본 그대로다). 그래서
    받은 바이트를 쌓아 두고 '남은 길이' 필드를 보며 하나씩 잘라 내야 한다.
    """

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def next_packet(self, timeout=1.0):
        """패킷 하나를 꺼낸다. 시간 안에 못 꺼내면 None을 돌려준다."""
        while True:
            msg, rest = mqtt.decode(self.buffer)
            if msg is not None:
                self.buffer = rest
                return msg
            self.sock.settimeout(timeout)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("브로커가 연결을 닫았다")
            self.buffer += chunk


def main():
    ap = argparse.ArgumentParser(description="MQTT 구독자")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic", default=TOPIC, help="주제 필터. + 와 # 를 쓸 수 있다")
    ap.add_argument("--qos", type=int, default=0, choices=[0, 1])
    ap.add_argument("--persist", action="store_true",
                    help="clean_session=False 로 붙는다. 끊겨도 세션이 남는다")
    ap.add_argument("--client-id", default="subscriber-1")
    ap.add_argument("--count", type=int, default=0, help="이만큼 받으면 끝낸다 (0이면 계속)")
    ap.add_argument("--timeout", type=float, default=0, help="이 초만큼만 기다린다")
    args = ap.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as exc:
        print(f"브로커에 붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 브로커를 띄운다: python3 broker.py", file=sys.stderr)
        return 1

    conn = Connection(sock)
    sock.sendall(mqtt.connect(args.client_id, clean_session=not args.persist))
    ack = conn.next_packet(timeout=5)
    if ack is None or ack["type"] != mqtt.CONNACK:
        print("CONNACK을 받지 못했다.", file=sys.stderr)
        return 1
    print(f"CONNACK: {mqtt.CONNACK_REASONS.get(ack['code'], ack['code'])}, "
          f"되살린 세션={ack['session_present']}")
    if args.persist and not ack["session_present"]:
        print("  세션이 없어 새로 만들었다. 이번에 끊고 다시 붙으면 True가 나온다.")
    if ack["session_present"]:
        print("  브로커가 예전 구독을 기억한다. 쌓아 둔 값이 곧바로 올 수 있다.")

    sock.sendall(mqtt.subscribe(1, [(args.topic, args.qos)]))
    print(f"SUBSCRIBE 보냄: {args.topic} (QoS {args.qos})")
    print(f"기다린다 (clean_session={not args.persist}). 멈추려면 Ctrl+C\n")

    received, started, subacked = 0, time.time(), False
    try:
        while True:
            if args.timeout and time.time() - started > args.timeout:
                print(f"\n{args.timeout}초가 지났다. 받은 것 {received}건.")
                break
            if args.count and received >= args.count:
                print(f"\n{args.count}건을 받아 끝낸다.")
                break

            msg = conn.next_packet(timeout=0.5)
            if msg is None:
                continue

            if msg["type"] == mqtt.SUBACK:
                subacked = True
                print(f"SUBACK: QoS {msg['codes'][0]} 로 받아 준다")
                continue

            if msg["type"] != mqtt.PUBLISH:
                continue

            received += 1
            marks = []
            if msg["retain"]:
                marks.append("retain된 값")
            if not subacked:
                marks.append("SUBACK보다 먼저 왔다 — 쌓아 둔 값이다")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            print(f"[{received}] {msg['topic']} = {msg['payload'].decode(errors='replace')}"
                  f"  (QoS {msg['qos']}, 전체 {msg['size']}바이트){suffix}")
            if msg["qos"] == 1:
                sock.sendall(mqtt.puback(msg["packet_id"]))
    except KeyboardInterrupt:
        print(f"\n멈춘다. 받은 것 {received}건.")
    except ConnectionError as exc:
        print(f"\n{exc}")
    finally:
        try:
            sock.sendall(mqtt.disconnect())
        except OSError:
            pass
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
