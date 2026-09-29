#!/usr/bin/env python3
"""캡처에서 MQTT 패킷을 뽑아 읽는다.

TCP 스트림을 다시 이어 붙여야 한다는 점이 이 파서의 핵심이다. 03 폴더에서 본
대로 TCP는 메시지 경계를 지켜 주지 않는다. MQTT 패킷 하나가 TCP 세그먼트 두
개에 걸쳐 오기도 하고, 세그먼트 하나에 MQTT 패킷 세 개가 담겨 오기도 한다.

그래서 흐름(출발지/목적지 짝)마다 바이트를 쌓아 두고, '남은 길이' 필드를 보며
패킷을 하나씩 잘라 낸다. 실제 프로토콜 분석기가 하는 일이 이것이다.

    sudo tcpdump -i lo0 -w samples/mqtt.pcap port 1883
    python3 broker.py &
    python3 publisher.py 23.5 --retain
    python3 parse_mqtt.py samples/mqtt.pcap
"""

import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mqtt  # noqa: E402
from tools.hexdump import ipv4  # noqa: E402
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="캡처에서 MQTT 패킷을 읽는다")
    ap.add_argument("pcap")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    streams = {}          # {(출발지, 목적지): 아직 안 쓴 바이트}
    counts, total_wire, total_payload = {}, 0, 0

    with f:
        print(f"링크 종류: {f.linktype_name}\n")
        for ts, data, _ in f:
            link_len, ip_pkt, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800 or len(ip_pkt) < 20 or ip_pkt[9] != 6:
                continue
            ihl = (ip_pkt[0] & 0x0F) * 4
            total_len = struct.unpack("!H", ip_pkt[2:4])[0]
            seg = ip_pkt[ihl:total_len]
            if len(seg) < 20:
                continue
            sport, dport = struct.unpack("!HH", seg[:4])
            if args.port not in (sport, dport):
                continue
            tcp_hlen = (struct.unpack("!H", seg[12:14])[0] >> 12) * 4
            payload = seg[tcp_hlen:]
            if not payload:
                continue

            key = (f"{ipv4(ip_pkt[12:16])}:{sport}", f"{ipv4(ip_pkt[16:20])}:{dport}")
            streams[key] = streams.get(key, b"") + payload

            # 쌓인 바이트에서 온전한 MQTT 패킷을 꺼낼 수 있을 때까지 꺼낸다.
            while True:
                msg, rest = mqtt.decode(streams[key])
                if msg is None:
                    break
                streams[key] = rest
                counts[msg["name"]] = counts.get(msg["name"], 0) + 1
                total_wire += msg["size"]

                line = f"[{ts:.6f}] {key[0]:>21} → {key[1]:<21} {msg['name']:<11} {msg['size']:>3}바이트"
                print(line)
                if msg["type"] == mqtt.CONNECT:
                    print(f"      client_id={msg['client_id']!r} clean_session={msg['clean_session']} "
                          f"keepalive={msg['keepalive']}초")
                elif msg["type"] == mqtt.CONNACK:
                    print(f"      {mqtt.CONNACK_REASONS.get(msg['code'], msg['code'])}, "
                          f"되살린 세션={msg['session_present']}")
                elif msg["type"] == mqtt.PUBLISH:
                    total_payload += len(msg["payload"])
                    print(f"      주제={msg['topic']!r} QoS={msg['qos']} retain={msg['retain']} "
                          f"본문 {len(msg['payload'])}바이트: {msg['payload'][:40]!r}")
                    overhead = msg["size"] - len(msg["payload"])
                    print(f"      MQTT가 쓴 바이트 {overhead} (주제 이름 {len(msg['topic'])} 포함)")
                elif msg["type"] == mqtt.SUBSCRIBE:
                    for topic, qos in msg["topics"]:
                        print(f"      구독 요청: {topic!r} QoS {qos}")

    print()
    if not counts:
        print(f"MQTT 패킷이 없다. 포트 {args.port} 를 잡았는지 본다.")
        return 0
    print("패킷 종류별 개수")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<12} {n}")
    print()
    print(f"MQTT 계층에서 오간 바이트 합계 {total_wire}, 그 가운데 실제 값 {total_payload}")
    if total_wire:
        print(f"값이 차지하는 비율 {total_payload / total_wire * 100:.1f}%")
    print("여기에 아직 TCP 헤더, IP 헤더, 이더넷 헤더가 더 붙는다. 06 폴더가 그것을 센다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
