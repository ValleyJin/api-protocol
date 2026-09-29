"""WebSocket 프레임을 만들고 읽는 최소 구현 (RFC 6455).

WebSocket은 HTTP로 시작해 HTTP를 버린다. 처음 한 번은 평범한 HTTP 요청을
보내되 "이 연결을 WebSocket으로 바꿔 달라"고 적는다. 서버가 101로 답하면
그때부터 같은 TCP 연결 위에서 프레임을 주고받는다.

    클라이언트 → GET /ws HTTP/1.1
                 Upgrade: websocket
                 Sec-WebSocket-Key: <무작위 16바이트를 base64로>
    서버      → HTTP/1.1 101 Switching Protocols
                 Sec-WebSocket-Accept: base64(sha1(key + 고정 GUID))

Accept 값을 계산해 돌려주는 까닭은 암호가 아니라 확인이다. 중간의 캐시 서버가
아무 생각 없이 101을 흉내 내는 일을 막으려는 장치다.

프레임 꼴은 이렇다.

    ┌─┬─┬─┬─┬───────┬─┬─────────┬─────────────┬──────────┐
    │F│R│R│R│ opcode│M│ 길이(7) │ 확장 길이   │ 마스크키 │ + 본문
    │I│S│S│S│  (4)  │A│         │ (0/2/8바이트)│(0/4바이트)│
    │N│V│V│V│       │S│         │             │          │
    └─┴─┴─┴─┴───────┴─┴─────────┴─────────────┴──────────┘

길이 필드가 3단이다. 125까지는 7비트에 그대로 적고, 126이면 뒤에 2바이트,
127이면 8바이트를 더 읽는다. 짧은 메시지를 짧게 적으려는 설계다.

클라이언트가 보내는 프레임은 반드시 마스킹한다. 본문 각 바이트를 4바이트
마스크 키와 XOR한다. 암호가 아니다. 중간의 낡은 프록시가 본문을 HTTP 요청으로
잘못 읽고 엉뚱한 짓을 하는 일(cache poisoning)을 막으려는 장치다.
"""

import base64
import hashlib
import os
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # RFC 6455가 못 박은 값

OP_CONT, OP_TEXT, OP_BINARY = 0x0, 0x1, 0x2
OP_CLOSE, OP_PING, OP_PONG = 0x8, 0x9, 0xA
OP_NAMES = {0x0: "이어짐", 0x1: "텍스트", 0x2: "바이너리",
            0x8: "닫기", 0x9: "핑", 0xA: "퐁"}


def accept_key(client_key: str) -> str:
    """Sec-WebSocket-Accept 값을 구한다."""
    digest = hashlib.sha1((client_key + GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def new_key() -> str:
    """무작위 16바이트를 base64로 적어 Sec-WebSocket-Key를 만든다."""
    return base64.b64encode(os.urandom(16)).decode()


def encode_frame(payload, opcode=OP_TEXT, mask=False, fin=True):
    """프레임 하나를 바이트로 만든다. mask=True면 클라이언트가 보내는 꼴이 된다."""
    if isinstance(payload, str):
        payload = payload.encode()

    first = (0x80 if fin else 0) | opcode
    length = len(payload)
    mask_bit = 0x80 if mask else 0

    if length < 126:
        header = bytes([first, mask_bit | length])
    elif length < 65536:
        header = bytes([first, mask_bit | 126]) + struct.pack("!H", length)
    else:
        header = bytes([first, mask_bit | 127]) + struct.pack("!Q", length)

    if not mask:
        return header + payload

    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return header + key + masked


def decode_frame(data):
    """프레임 하나를 읽는다. 다 오지 않았으면 (None, 원래 바이트)를 돌려준다."""
    if len(data) < 2:
        return None, data
    first, second = data[0], data[1]
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    offset = 2

    if length == 126:
        if len(data) < offset + 2:
            return None, data
        length = struct.unpack("!H", data[offset:offset + 2])[0]
        offset += 2
    elif length == 127:
        if len(data) < offset + 8:
            return None, data
        length = struct.unpack("!Q", data[offset:offset + 8])[0]
        offset += 8

    key = b""
    if masked:
        if len(data) < offset + 4:
            return None, data
        key = data[offset:offset + 4]
        offset += 4

    if len(data) < offset + length:
        return None, data

    payload = data[offset:offset + length]
    if masked:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))

    frame = {"fin": fin, "opcode": opcode, "opcode_name": OP_NAMES.get(opcode, opcode),
             "masked": masked, "payload": payload, "size": offset + length,
             "header_size": offset}
    return frame, data[offset + length:]


def parse_http_headers(raw: bytes):
    """핸드셰이크 요청이나 응답에서 첫 줄과 헤더를 가른다."""
    text = raw.decode("latin-1")
    lines = text.split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return lines[0], headers
