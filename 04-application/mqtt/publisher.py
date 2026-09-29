#!/usr/bin/env python3
"""MQTT 발행자. 공통 과제의 센서 값을 주제에 올린다.

paho-mqtt를 쓰지 않는다. mqtt.py로 패킷을 직접 만들어 브로커에 보낸다.
그래야 선 위를 흐르는 바이트가 몇 개인지 눈으로 셀 수 있다.

    python3 publisher.py 23.5
    python3 publisher.py 23.5 --retain            # 브로커가 들고 있게 한다
    python3 publisher.py 23.5 --qos 1             # 브로커가 PUBACK을 준다
    python3 publisher.py --repeat 5 --interval 1  # 다섯 번 올린다
"""

import argparse
import pathlib
import socket
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mqtt  # noqa: E402
from common.sensor import TOPIC, encode_compact, reading  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="MQTT 발행자")
    ap.add_argument("value", nargs="?", type=float, help="올릴 온도. 없으면 지어낸다")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--qos", type=int, default=0, choices=[0, 1])
    ap.add_argument("--retain", action="store_true")
    ap.add_argument("--client-id", default="publisher-1")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as exc:
        print(f"브로커에 붙지 못했다: {exc}", file=sys.stderr)
        print("먼저 브로커를 띄운다: python3 broker.py", file=sys.stderr)
        return 1

    connect_packet = mqtt.connect(args.client_id)
    sock.sendall(connect_packet)
    msg, _ = mqtt.decode(sock.recv(4096))
    print(f"CONNECT {len(connect_packet)}바이트 보냄 → "
          f"CONNACK: {mqtt.CONNACK_REASONS.get(msg['code'], msg['code'])}")

    total_wire, total_payload = len(connect_packet) + 4, 0
    for i in range(args.repeat):
        data = reading(args.value)
        payload = encode_compact(data)     # 값만 적는다. 센서 이름은 주제가 말해 준다
        packet = mqtt.publish(args.topic, payload, args.qos, i + 1 if args.qos else None,
                              args.retain)
        sock.sendall(packet)
        total_wire += len(packet)
        total_payload += len(payload)
        print(f"PUBLISH {len(packet):>3}바이트  주제={args.topic}  값={payload.decode()}"
              f"  QoS={args.qos}  retain={args.retain}")

        if args.qos == 1:
            ack, _ = mqtt.decode(sock.recv(4096))
            total_wire += 4
            print(f"  ← PUBACK (packet_id={ack['packet_id']}) — 브로커가 받았다고 확인해 준다")

        if i < args.repeat - 1:
            time.sleep(args.interval)

    sock.sendall(mqtt.disconnect())
    sock.close()

    print()
    print(f"오간 바이트 합계 {total_wire}, 그 가운데 실제 값 {total_payload}")
    print(f"값이 차지하는 비율 {total_payload / total_wire * 100:.1f}%")
    print()
    print("견줄 것")
    print(f"  MQTT PUBLISH 한 건: {len(packet)}바이트 (본문 {len(payload)})")
    print("  HTTP PUT 한 건    : 약 200바이트 (본문 20)")
    print("  CoAP PUT 한 건    : 44바이트 (본문 4)")
    print("  MQTT는 주제 이름을 매번 실어 보내므로 주제가 길면 그만큼 불어난다.")
    print("  대신 한 번 붙어 두면 여러 건을 그 연결로 계속 보낸다. HTTP는 매번 새로 붙는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
