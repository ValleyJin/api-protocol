#!/usr/bin/env python3
"""MQTT 브로커를 직접 만든다. Mosquitto를 깔지 않아도 실습이 된다.

브로커가 하는 일은 셋이다.

    1. 접속을 받고 client id로 세션을 기억한다
    2. 구독 목록을 들고 있다가
    3. PUBLISH가 오면 주제가 맞는 구독자에게 나눠 준다

여기서 retain과 clean session이 왜 필요한지 코드로 드러난다.

    retain        : 마지막 한 건을 주제마다 들고 있다가, 새로 구독한 사람에게
                    곧바로 한 번 보내 준다. 안 그러면 다음 값이 올 때까지
                    새 구독자는 아무것도 모른다.
    clean session : 구독자가 끊겨 있는 동안 온 QoS 1 메시지를 쌓아 두었다가
                    다시 붙으면 몰아 준다. QoS 0은 쌓지 않는다. 그래서 발행자도
                    QoS 1 이상으로 올려야 이 실습이 눈에 보인다.

    python3 broker.py
    python3 broker.py --port 1884 -v
"""

import argparse
import pathlib
import socket
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mqtt  # noqa: E402


class Session:
    """client id 하나에 딸린 상태. clean_session이 False면 끊겨도 남는다."""

    def __init__(self, client_id):
        self.client_id = client_id
        self.subscriptions = {}     # {주제 필터: QoS}
        self.queue = []             # 끊겨 있는 동안 쌓인 (주제, 본문, QoS)
        self.conn = None


class Broker:
    def __init__(self, verbose=True):
        self.sessions = {}          # {client_id: Session}
        self.retained = {}          # {주제: (본문, QoS)}
        self.lock = threading.Lock()
        self.verbose = verbose
        self.next_packet_id = 1

    def log(self, *parts):
        if self.verbose:
            print("[브로커]", *parts, flush=True)

    def take_packet_id(self):
        with self.lock:
            pid = self.next_packet_id
            self.next_packet_id = self.next_packet_id % 65535 + 1
            return pid

    # ── 접속 ──────────────────────────────────────────────────────────
    def on_connect(self, conn, msg):
        client_id = msg["client_id"] or f"anon-{id(conn) & 0xFFFF}"
        clean = msg["clean_session"]

        with self.lock:
            old = self.sessions.get(client_id)
            if clean or old is None:
                if old is not None:
                    self.log(f"{client_id}: clean session이라 예전 세션을 버린다")
                session = Session(client_id)
                self.sessions[client_id] = session
                session_present = False
            else:
                session = old
                session_present = True
                self.log(f"{client_id}: 예전 세션을 되살렸다 "
                         f"(구독 {len(session.subscriptions)}개, 쌓인 메시지 {len(session.queue)}개)")
            session.conn = conn
            session.clean = clean

        conn.sendall(mqtt.connack(session_present, 0))
        self.log(f"{client_id} 접속 (clean_session={clean}, 되살린 세션={session_present})")

        # 끊겨 있는 동안 쌓인 것을 몰아 보낸다. 이것이 clean_session=False의 값이다.
        if session.queue:
            self.log(f"{client_id}: 쌓아 둔 {len(session.queue)}건을 몰아 보낸다")
            for topic, payload, qos in session.queue:
                self.deliver(session, topic, payload, qos)
            session.queue.clear()
        return session

    # ── 구독 ──────────────────────────────────────────────────────────
    def on_subscribe(self, session, msg):
        codes = []
        for topic, qos in msg["topics"]:
            session.subscriptions[topic] = qos
            codes.append(qos)
            self.log(f"{session.client_id} 구독: {topic} (QoS {qos})")
        session.conn.sendall(mqtt.suback(msg["packet_id"], codes))

        # 새로 구독한 사람에게 retain된 값을 곧바로 한 번 보낸다.
        with self.lock:
            retained = list(self.retained.items())
        for topic, (payload, qos) in retained:
            for filter_, sub_qos in session.subscriptions.items():
                if mqtt.topic_matches(filter_, topic):
                    self.log(f"{session.client_id}: retain된 {topic} 을 바로 보낸다")
                    self.deliver(session, topic, payload, min(qos, sub_qos), retain=True)
                    break

    # ── 발행 ──────────────────────────────────────────────────────────
    def on_publish(self, session, msg):
        topic, payload, qos = msg["topic"], msg["payload"], msg["qos"]
        self.log(f"{session.client_id} 발행: {topic} = {payload[:40]!r} "
                 f"(QoS {qos}, retain {msg['retain']})")

        if msg["retain"]:
            with self.lock:
                if payload:
                    self.retained[topic] = (payload, qos)
                else:
                    self.retained.pop(topic, None)   # 빈 본문은 retain을 지우라는 뜻이다

        if qos == 1:
            session.conn.sendall(mqtt.puback(msg["packet_id"]))

        with self.lock:
            targets = list(self.sessions.values())

        for target in targets:
            for filter_, sub_qos in target.subscriptions.items():
                if not mqtt.topic_matches(filter_, topic):
                    continue
                # 실제 전달 QoS는 발행 QoS와 구독 QoS 가운데 작은 쪽이다.
                effective = min(qos, sub_qos)
                if target.conn is not None:
                    self.deliver(target, topic, payload, effective)
                elif effective >= 1 and not getattr(target, "clean", True):
                    # 끊긴 구독자. QoS 1 이상일 때만 쌓는다. QoS 0은 버린다.
                    target.queue.append((topic, payload, effective))
                    self.log(f"{target.client_id} 는 끊겨 있다. QoS {effective} 라 쌓아 둔다 "
                             f"(쌓인 것 {len(target.queue)}건)")
                break

    def deliver(self, session, topic, payload, qos, retain=False):
        if session.conn is None:
            return
        pid = self.take_packet_id() if qos > 0 else None
        try:
            session.conn.sendall(mqtt.publish(topic, payload, qos, pid, retain))
        except OSError:
            session.conn = None

    # ── 연결 하나 ─────────────────────────────────────────────────────
    def handle(self, conn, addr):
        session, buffer = None, b""
        try:
            conn.settimeout(300)
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    msg, buffer = mqtt.decode(buffer)
                    if msg is None:
                        break
                    if msg["type"] == mqtt.CONNECT:
                        session = self.on_connect(conn, msg)
                    elif session is None:
                        return      # CONNECT 없이 다른 패킷을 보내면 끊는다
                    elif msg["type"] == mqtt.SUBSCRIBE:
                        self.on_subscribe(session, msg)
                    elif msg["type"] == mqtt.PUBLISH:
                        self.on_publish(session, msg)
                    elif msg["type"] == mqtt.PINGREQ:
                        conn.sendall(mqtt.pingresp())
                    elif msg["type"] == mqtt.DISCONNECT:
                        return
        except (OSError, ValueError):
            pass
        finally:
            if session is not None:
                session.conn = None
                clean = getattr(session, "clean", True)
                if clean:
                    with self.lock:
                        self.sessions.pop(session.client_id, None)
                    self.log(f"{session.client_id} 끊김 — clean session이라 상태를 지운다")
                else:
                    self.log(f"{session.client_id} 끊김 — 세션은 남겨 둔다 "
                             f"(구독 {len(session.subscriptions)}개)")
            conn.close()


def main():
    ap = argparse.ArgumentParser(description="직접 만든 MQTT 브로커")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    broker = Broker(verbose=not args.quiet)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(32)
    print(f"[브로커] mqtt://{args.host}:{args.port} 에서 기다린다. 멈추려면 Ctrl+C", flush=True)

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=broker.handle, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[브로커] 멈춘다.")
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
