#!/usr/bin/env python3
"""실습용 표본 pcap을 만든다.

**이 파일이 만드는 것은 잡은 캡처가 아니라 지어낸 캡처다.** 이더넷, IP, TCP
헤더를 규격대로 조립해 pcap 파일로 적는다. 바이트는 진짜와 같은 규격이지만
실제 망에서 오간 것은 아니다.

왜 이런 것을 두는가. 캡처를 뜨려면 관리자 권한이 필요하다. 권한이 없거나
공용 기기에서 실습하는 사람도 파서를 돌려 볼 수 있어야 해서 만들었다.

**직접 캡처를 뜰 수 있으면 그쪽을 쓴다.** 진짜 캡처에는 재전송, 순서 뒤바뀜,
TCP 옵션 같은 것이 들어 있다. 여기서 만든 것은 깨끗해서 그런 것이 없다.

    python3 tools/make_sample_pcap.py 06-encapsulation/samples/sample.pcap
"""

import argparse
import pathlib
import struct
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def checksum(data):
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def build_frame(src_mac, dst_mac, src_ip, dst_ip, sport, dport, seq, ack, flags,
                payload=b"", tcp_options=b""):
    """이더넷 + IP + TCP + 본문을 한 프레임으로 조립한다."""
    if len(tcp_options) % 4:
        tcp_options += b"\x00" * (4 - len(tcp_options) % 4)
    tcp_hlen = 20 + len(tcp_options)

    tcp = struct.pack("!HHIIHHHH", sport, dport, seq, ack,
                      ((tcp_hlen // 4) << 12) | flags, 65535, 0, 0) + tcp_options

    # TCP 체크섬은 가짜 헤더(pseudo header)를 앞에 붙여 구한다.
    pseudo = struct.pack("!4s4sBBH", src_ip, dst_ip, 0, 6, len(tcp) + len(payload))
    tcp = tcp[:16] + struct.pack("!H", checksum(pseudo + tcp + payload)) + tcp[18:]

    total_len = 20 + len(tcp) + len(payload)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total_len, 0x1234, 0x4000, 64, 6, 0,
                     src_ip, dst_ip)
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]

    eth = struct.pack("!6s6sH", dst_mac, src_mac, 0x0800)
    return eth + ip + tcp + payload


def write_pcap(path, frames, linktype=1):
    """pcap 파일로 적는다. 전역 헤더 24바이트 + [패킷 헤더 16 + 데이터] 되풀이."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype))
        base = time.time()
        for i, frame in enumerate(frames):
            ts = base + i * 0.001
            fh.write(struct.pack("<IIII", int(ts), int((ts % 1) * 1e6), len(frame), len(frame)))
            fh.write(frame)


def main():
    ap = argparse.ArgumentParser(description="실습용 표본 pcap을 만든다")
    ap.add_argument("out", nargs="?", default="06-encapsulation/samples/sample.pcap")
    args = ap.parse_args()

    client_mac = bytes.fromhex("aabbccddee01")
    server_mac = bytes.fromhex("aabbccddee02")
    client_ip = bytes([192, 168, 0, 10])
    server_ip = bytes([192, 168, 0, 20])

    # 타임스탬프 옵션. 요즘 운영체제가 기본으로 켜 두는 것이라 헤더가 32바이트가 된다.
    ts_option = b"\x01\x01\x08\x0a" + struct.pack("!II", 111111, 222222)

    frames = []

    # ── HTTP 흐름 (포트 8080) ────────────────────────────────────────
    http_request = (
        "GET /sensors/living-room/temperature HTTP/1.1\r\n"
        "Host: 192.168.0.20:8080\r\n"
        "Connection: close\r\n"
        "User-Agent: raw-socket-client/1.0\r\n\r\n"
    ).encode()
    http_body = b'{"sensor":"living-room","temperature":21.0,"unit":"C","ts":1700000000.0}'
    http_response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(http_body)}\r\n"
        "Connection: close\r\n"
        "Server: minimal-socket-server/1.0\r\n\r\n"
    ).encode() + http_body

    c, s = 1000, 5000
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51000, 8080,
                              c, 0, 0x002, tcp_options=b"\x02\x04\x05\xb4" + ts_option))   # SYN
    frames.append(build_frame(server_mac, client_mac, server_ip, client_ip, 8080, 51000,
                              s, c + 1, 0x012, tcp_options=b"\x02\x04\x05\xb4" + ts_option))  # SYN+ACK
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51000, 8080,
                              c + 1, s + 1, 0x010, tcp_options=ts_option))                  # ACK
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51000, 8080,
                              c + 1, s + 1, 0x018, http_request, ts_option))                # PSH+ACK
    frames.append(build_frame(server_mac, client_mac, server_ip, client_ip, 8080, 51000,
                              s + 1, c + 1 + len(http_request), 0x018, http_response, ts_option))
    frames.append(build_frame(server_mac, client_mac, server_ip, client_ip, 8080, 51000,
                              s + 1 + len(http_response), c + 1 + len(http_request), 0x011,
                              tcp_options=ts_option))                                       # FIN+ACK
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51000, 8080,
                              c + 1 + len(http_request), s + 2 + len(http_response), 0x011,
                              tcp_options=ts_option))                                       # FIN+ACK

    # ── MQTT 흐름 (포트 1883) ────────────────────────────────────────
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "04-application" / "mqtt"))
    import mqtt

    c2, s2 = 2000, 6000
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51001, 1883,
                              c2, 0, 0x002, tcp_options=b"\x02\x04\x05\xb4" + ts_option))
    frames.append(build_frame(server_mac, client_mac, server_ip, client_ip, 1883, 51001,
                              s2, c2 + 1, 0x012, tcp_options=b"\x02\x04\x05\xb4" + ts_option))
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51001, 1883,
                              c2 + 1, s2 + 1, 0x010, tcp_options=ts_option))

    connect = mqtt.connect("publisher-1")
    frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51001, 1883,
                              c2 + 1, s2 + 1, 0x018, connect, ts_option))
    connack = mqtt.connack()
    frames.append(build_frame(server_mac, client_mac, server_ip, client_ip, 1883, 51001,
                              s2 + 1, c2 + 1 + len(connect), 0x018, connack, ts_option))

    seq = c2 + 1 + len(connect)
    for value in (b"21.0", b"21.3", b"21.5"):
        packet = mqtt.publish("home/living-room/temperature", value)
        frames.append(build_frame(client_mac, server_mac, client_ip, server_ip, 51001, 1883,
                                  seq, s2 + 1 + len(connack), 0x018, packet, ts_option))
        seq += len(packet)

    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pcap(path, frames)

    print(f"{path} 를 만들었다. 프레임 {len(frames)}개, {path.stat().st_size}바이트")
    print()
    print("들어 있는 것")
    print(f"  HTTP 흐름 (포트 8080): 핸드셰이크 3 + 요청 1 + 응답 1 + 종료 2 = 7프레임")
    print(f"  MQTT 흐름 (포트 1883): 핸드셰이크 3 + CONNECT/CONNACK 2 + PUBLISH 3 = 8프레임")
    print()
    print("다시 말하지만 이것은 지어낸 캡처다. 진짜 캡처를 뜰 수 있으면 그쪽을 쓴다.")
    print("  sudo tcpdump -i lo0 -w my.pcap port 8080 or port 1883")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
