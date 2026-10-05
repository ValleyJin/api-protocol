"""MQTT 3.1.1 패킷을 만들고 읽는 최소 구현.

MQTT는 요청-응답이 아니다. 보내는 쪽(발행자)과 받는 쪽(구독자)이 서로를 모른 채
'주제(topic)'로만 이어진다. 가운데에 브로커가 서서 주제별로 나눠 준다.

    발행자 ──PUBLISH──▶ 브로커 ──PUBLISH──▶ 구독자
                          ▲
                  구독자가 미리 SUBSCRIBE 해 둔 주제로만 간다

패킷은 모두 같은 꼴로 시작한다.

    ┌───────────────┬───────────────┐
    │ 종류(4) 플래그(4) │  남은 길이(1~4) │  + 가변 헤더 + 본문
    └───────────────┴───────────────┘

'남은 길이'는 한 바이트에 7비트씩 담고 맨 앞 비트로 "아직 더 있다"를 표시한다.
그래서 짧은 메시지는 길이 필드가 1바이트로 끝난다. HTTP의 Content-Length가
글자 여러 개를 쓰는 것과 견줘 보면 설계 방향이 그대로 드러난다.

    CONNECT 1   접속하겠다        SUBSCRIBE 8   이 주제를 받겠다
    CONNACK 2   받았다            SUBACK    9   받았다
    PUBLISH 3   이 값을 알린다    PINGREQ  12   살아 있나
    PUBACK  4   잘 받았다(QoS 1)  DISCONNECT 14 끊는다
"""

import struct

CONNECT, CONNACK, PUBLISH, PUBACK = 1, 2, 3, 4
PUBREC, PUBREL, PUBCOMP = 5, 6, 7
SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK = 8, 9, 10, 11
PINGREQ, PINGRESP, DISCONNECT = 12, 13, 14

NAMES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 5: "PUBREC",
         6: "PUBREL", 7: "PUBCOMP", 8: "SUBSCRIBE", 9: "SUBACK", 10: "UNSUBSCRIBE",
         11: "UNSUBACK", 12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}

CONNACK_REASONS = {0: "접속 승인", 1: "프로토콜 판본이 안 맞다", 2: "client id를 거절",
                   3: "서버를 쓸 수 없다", 4: "이름이나 비밀번호가 틀렸다", 5: "권한이 없다"}


# MQTT 3.1.1은 남은 길이를 4바이트까지만 허용한다. 그 상한이 268435455다.
MAX_REMAINING_LENGTH = 268435455


def encode_varint(n: int) -> bytes:
    """남은 길이를 7비트씩 잘라 적는다. 127까지는 1바이트로 끝난다."""
    if n < 0:
        raise ValueError("남은 길이가 음수다")
    if n > MAX_REMAINING_LENGTH:
        raise ValueError(f"남은 길이는 {MAX_REMAINING_LENGTH}를 넘을 수 없다")
    out = b""
    while True:
        byte = n % 128
        n //= 128
        if n:
            byte |= 0x80        # 맨 앞 비트가 "뒤에 더 있다"는 표시
        out += bytes([byte])
        if not n:
            return out


def decode_varint(data, offset=0):
    """(값, 다음 위치)를 돌려준다."""
    value, multiplier, count = 0, 1, 0
    while True:
        if offset >= len(data):
            raise ValueError("남은 길이를 다 읽지 못했다")
        byte = data[offset]
        offset += 1
        value += (byte & 0x7F) * multiplier
        count += 1
        if not byte & 0x80:
            return value, offset
        multiplier *= 128
        # 이 자리는 "뒤에 더 있다" 표시를 이미 확인한 뒤다. 네 바이트를 읽고도
        # 표시가 서 있으면 명세를 넘은 것이니 다섯째 바이트를 읽기 전에 거른다.
        if count >= 4:
            raise ValueError("남은 길이가 4바이트를 넘는다")


def _str(value: str) -> bytes:
    """MQTT 문자열은 2바이트 길이를 앞에 붙인 UTF-8이다."""
    raw = value.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def _read_str(data, offset):
    length = struct.unpack("!H", data[offset:offset + 2])[0]
    offset += 2
    return data[offset:offset + length].decode("utf-8", "replace"), offset + length


def _packet(ptype, flags, body):
    return bytes([(ptype << 4) | flags]) + encode_varint(len(body)) + body


def connect(client_id, keepalive=60, clean_session=True):
    """접속 패킷. clean_session이 False면 브로커가 내 세션을 기억한다."""
    body = _str("MQTT") + bytes([4])            # 판본 4 = MQTT 3.1.1
    flags = 0x02 if clean_session else 0x00     # 비트 1 = clean session
    body += bytes([flags]) + struct.pack("!H", keepalive) + _str(client_id)
    return _packet(CONNECT, 0, body)


def connack(session_present=False, code=0):
    return _packet(CONNACK, 0, bytes([1 if session_present else 0, code]))


def publish(topic, payload, qos=0, packet_id=None, retain=False, dup=False):
    """값을 알린다. retain을 켜면 브로커가 마지막 한 건을 들고 있는다."""
    if isinstance(payload, str):
        payload = payload.encode()
    body = _str(topic)
    if qos > 0:
        if packet_id is None:
            raise ValueError("QoS 1 이상에는 packet_id가 필요하다")
        body += struct.pack("!H", packet_id)
    body += payload
    flags = (qos << 1) | (0x01 if retain else 0) | (0x08 if dup else 0)
    return _packet(PUBLISH, flags, body)


def puback(packet_id):
    return _packet(PUBACK, 0, struct.pack("!H", packet_id))


def subscribe(packet_id, topics):
    """topics는 (주제 필터, QoS) 목록이다."""
    body = struct.pack("!H", packet_id)
    for topic, qos in topics:
        body += _str(topic) + bytes([qos])
    return _packet(SUBSCRIBE, 0x02, body)   # SUBSCRIBE는 플래그가 0010으로 고정이다


def suback(packet_id, codes):
    return _packet(SUBACK, 0, struct.pack("!H", packet_id) + bytes(codes))


def pingreq():
    return _packet(PINGREQ, 0, b"")


def pingresp():
    return _packet(PINGRESP, 0, b"")


def disconnect():
    return _packet(DISCONNECT, 0, b"")


def decode(data):
    """패킷 하나를 읽는다. 다 오지 않았으면 None을 돌려준다."""
    if len(data) < 2:
        return None, data
    ptype = data[0] >> 4
    flags = data[0] & 0x0F
    try:
        remaining, offset = decode_varint(data, 1)
    except ValueError:
        return None, data
    if len(data) < offset + remaining:
        return None, data          # 아직 다 오지 않았다. 더 읽어야 한다

    body = data[offset:offset + remaining]
    rest = data[offset + remaining:]
    msg = {"type": ptype, "name": NAMES.get(ptype, ptype), "flags": flags,
           "size": offset + remaining, "remaining": remaining}

    if ptype == CONNECT:
        name, pos = _read_str(body, 0)
        level = body[pos]
        cflags = body[pos + 1]
        keepalive = struct.unpack("!H", body[pos + 2:pos + 4])[0]
        client_id, _ = _read_str(body, pos + 4)
        msg.update(protocol=name, level=level, clean_session=bool(cflags & 0x02),
                   keepalive=keepalive, client_id=client_id)
    elif ptype == CONNACK:
        msg.update(session_present=bool(body[0]), code=body[1])
    elif ptype == PUBLISH:
        qos = (flags >> 1) & 0x03
        topic, pos = _read_str(body, 0)
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack("!H", body[pos:pos + 2])[0]
            pos += 2
        msg.update(topic=topic, qos=qos, retain=bool(flags & 0x01),
                   dup=bool(flags & 0x08), packet_id=packet_id, payload=body[pos:])
    elif ptype in (PUBACK, PUBREC, PUBREL, PUBCOMP, UNSUBACK):
        msg.update(packet_id=struct.unpack("!H", body[:2])[0])
    elif ptype == SUBSCRIBE:
        packet_id = struct.unpack("!H", body[:2])[0]
        pos, topics = 2, []
        while pos < len(body):
            topic, pos = _read_str(body, pos)
            topics.append((topic, body[pos]))
            pos += 1
        msg.update(packet_id=packet_id, topics=topics)
    elif ptype == SUBACK:
        msg.update(packet_id=struct.unpack("!H", body[:2])[0], codes=list(body[2:]))

    return msg, rest


def topic_matches(filter_, topic):
    """주제 필터가 주제와 맞는지 본다. +는 한 칸, #는 그 아래 전부를 뜻한다.

        home/+/temperature  는 home/living-room/temperature 와 맞는다
        home/#              는 home 아래 전부와 맞는다
    """
    f_parts, t_parts = filter_.split("/"), topic.split("/")
    for i, f in enumerate(f_parts):
        if f == "#":
            return True
        if i >= len(t_parts):
            return False
        if f != "+" and f != t_parts[i]:
            return False
    return len(f_parts) == len(t_parts)
