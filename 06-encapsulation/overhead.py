#!/usr/bin/env python3
"""캡처 전체를 훑어 계층별 오버헤드를 세고 프로토콜끼리 견준다.

peel.py 가 한 프레임을 벗겼다면 여기서는 흐름 전체를 센다. 값 하나를 나르는
데 실제로 얼마가 드는지, 프로토콜을 바꾸면 얼마나 달라지는지 숫자로 나온다.

    python3 ../tools/make_sample_pcap.py samples/sample.pcap
    python3 overhead.py samples/sample.pcap
"""

import argparse
import pathlib
import struct
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "04-application" / "mqtt"))
from tools.pcap import PcapError, PcapFile, strip_link_header  # noqa: E402

KNOWN_PORTS = {80: "HTTP", 8080: "HTTP", 8000: "HTTP", 9200: "HTTP",
               1883: "MQTT", 5683: "CoAP", 53: "DNS", 8081: "WebSocket", 9500: "WebSocket"}


def app_name(sport, dport):
    for port in (sport, dport):
        if port in KNOWN_PORTS:
            return KNOWN_PORTS[port]
    return f"포트 {min(sport, dport)}"


def mqtt_value_bytes(stream):
    """MQTT 스트림에서 실제 센서 값이 몇 바이트인지 센다."""
    import mqtt
    total, packets = 0, 0
    buffer = stream
    while True:
        msg, buffer = mqtt.decode(buffer)
        if msg is None:
            return total, packets
        packets += 1
        if msg["type"] == mqtt.PUBLISH:
            total += len(msg["payload"])


def http_body_bytes(stream):
    """HTTP 스트림에서 본문이 몇 바이트인지 센다."""
    total, messages = 0, 0
    pos = 0
    while True:
        sep = stream.find(b"\r\n\r\n", pos)
        if sep < 0:
            return total, messages
        head = stream[pos:sep].decode("latin-1", "replace")
        messages += 1
        length = 0
        for line in head.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = 0
        total += length
        pos = sep + 4 + length


def main():
    ap = argparse.ArgumentParser(description="계층별 오버헤드를 센다")
    ap.add_argument("pcap")
    args = ap.parse_args()

    try:
        f = PcapFile(args.pcap)
    except PcapError as exc:
        print(exc, file=sys.stderr)
        return 1

    # 방향마다 스트림을 따로 모은다. 요청과 응답을 한 바구니에 담으면 파싱이 깨진다.
    flows = defaultdict(lambda: {"frames": 0, "link": 0, "ip": 0, "tcp": 0, "app": 0,
                                 "c2s": b"", "s2c": b"", "total": 0})

    with f:
        print(f"파일      : {args.pcap}")
        print(f"링크 종류 : {f.linktype_name}")
        if f.linktype_name != "EN10MB":
            print()
            print("⚠ 이더넷이 아니다. 루프백이나 -i any 로 잡으면 이렇게 된다.")
            print("  실제 링크에서 오가는 프레임이 아니라 1층 오버헤드가 어긋난다.")
            print("  브로커를 다른 기기나 VM에 띄우고 물리 인터페이스에서 다시 잡는다.")
        print()

        for ts, data, orig_len in f:
            link_len, ip_pkt, ethertype = strip_link_header(f.linktype_name, data)
            if ethertype != 0x0800 or len(ip_pkt) < 20 or ip_pkt[9] != 6:
                continue
            ihl = (ip_pkt[0] & 0x0F) * 4
            total_len = struct.unpack("!H", ip_pkt[2:4])[0]
            seg = ip_pkt[ihl:total_len]
            if len(seg) < 20:
                continue
            sport, dport = struct.unpack("!HH", seg[:4])
            tcp_hlen = (struct.unpack("!H", seg[12:14])[0] >> 12) * 4
            payload = seg[tcp_hlen:]

            key = app_name(sport, dport)
            flow = flows[key]
            flow["frames"] += 1
            flow["link"] += link_len
            flow["ip"] += ihl
            flow["tcp"] += tcp_hlen
            flow["app"] += len(payload)
            flow["total"] += len(data)
            if dport in KNOWN_PORTS:
                flow["c2s"] += payload      # 클라이언트 → 서버 (요청)
            else:
                flow["s2c"] += payload      # 서버 → 클라이언트 (응답)

    if not flows:
        print("TCP 흐름을 찾지 못했다.")
        return 0

    print("=" * 86)
    print(f"{'프로토콜':<12}{'프레임':>7}{'1층':>8}{'2층 IP':>9}{'3층 TCP':>10}"
          f"{'4층 앱':>9}{'합계':>9}{'앱 비율':>9}")
    print("=" * 86)
    for name, flow in flows.items():
        ratio = flow["app"] / flow["total"] * 100 if flow["total"] else 0
        print(f"{name:<12}{flow['frames']:>7}{flow['link']:>8}{flow['ip']:>9}"
              f"{flow['tcp']:>10}{flow['app']:>9}{flow['total']:>9}{ratio:>8.1f}%")
    print("=" * 86)
    print()

    print("여기서 한 겹 더 벗긴다. 4층 바이트에도 프로토콜 자신의 헤더가 들어 있다.")
    print()
    results = {}
    for name, flow in flows.items():
        if name == "MQTT":
            # PUBLISH는 양쪽 다 오간다. 두 방향을 따로 세어 더한다.
            up, n1 = mqtt_value_bytes(flow["c2s"])
            down, n2 = mqtt_value_bytes(flow["s2c"])
            value, label = up + down, f"MQTT 패킷 {n1 + n2}개 중 PUBLISH 값"
        elif name == "HTTP":
            # 본문은 대개 응답에 실린다. 요청 본문(PUT, POST)도 함께 센다.
            up, n1 = http_body_bytes(flow["c2s"])
            down, n2 = http_body_bytes(flow["s2c"])
            value, label = up + down, f"HTTP 메시지 {n1 + n2}개의 본문"
        else:
            continue
        results[name] = (value, flow["total"])
        useful = value / flow["total"] * 100 if flow["total"] else 0
        print(f"  {name:<6} 전체 {flow['total']:>5}바이트 중 실제 값 {value:>4}바이트  "
              f"→ {useful:.1f}%    ({label})")

    if len(results) >= 2 and "MQTT" in results and "HTTP" in results:
        mqtt_value, mqtt_total = results["MQTT"]
        http_value, http_total = results["HTTP"]
        print()
        print("=" * 66)
        print("같은 값을 나르는 데 든 바이트")
        print("=" * 66)
        if mqtt_value and http_value:
            print(f"  HTTP: 값 1바이트를 나르는 데 {http_total / http_value:.1f}바이트를 썼다")
            print(f"  MQTT: 값 1바이트를 나르는 데 {mqtt_total / mqtt_value:.1f}바이트를 썼다")
        print()
        print("  이 숫자를 곧이곧대로 읽으면 안 된다. 두 가지가 비교를 비튼다.")
        print()
        print("  첫째, 실은 다른 것을 나르고 있다. HTTP는 센서 이름과 단위까지 담은 JSON을")
        print("  보냈고 MQTT는 숫자만 보냈다. 값 1바이트당 비용은 많이 담을수록 낮아지니,")
        print("  말이 많은 쪽이 오히려 좋아 보인다. 이 잣대 하나로 우열을 가릴 수 없다.")
        print()
        print("  둘째, 건수가 적다. HTTP는 연결을 맺고 끊는 데 다섯 프레임을 썼고 값은")
        print("  한 번 날랐다. MQTT는 연결 하나로 세 번 날랐다. 건수를 늘리면 MQTT는")
        print("  PUBLISH 프레임만 늘고 HTTP는 핸드셰이크까지 되풀이한다.")
        print()
        print("  제대로 견주려면 같은 것을 같은 횟수만큼 날라야 한다. 04-application 의")
        print("  common/sensor.py 가 그래서 있다. 캡처를 직접 떠서 건수를 바꿔 가며")
        print("  다시 세어 보면 어디서 순서가 뒤집히는지 보인다.")

    print()
    print("정리")
    print("  1층 14 + 2층 20 + 3층 20~36 = 프레임마다 54~70바이트가 그냥 붙는다.")
    print("  TCP 헤더는 타임스탬프 옵션만 붙으면 32, SYN처럼 MSS까지 붙으면 36이다.")
    print("  센서 값 4바이트를 보내려고 그 열 배가 넘는 바이트가 움직인다.")
    print("  좁은 망에서 프로토콜을 고르는 일이 왜 중요한지 이 숫자가 말해 준다.")
    print("  05-api-layers 의 여덟 방식도 결국 이 숫자 위에 얹힌다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
