"""CoAP 메시지를 만들고 읽는 최소 구현 (RFC 7252).

CoAP는 "저사양 기기를 위한 HTTP"라고 부를 만하다. GET, PUT 같은 메서드도 있고
응답 코드도 HTTP를 닮았다. 다른 점은 전부 '작게 만들기' 쪽으로 기울어 있다.

    HTTP  : 텍스트, TCP 위, 헤더 수백 바이트
    CoAP  : 바이너리, UDP 위, 헤더 4바이트

헤더가 4바이트다. HTTP의 `GET / HTTP/1.1\\r\\nHost: ...` 한 줄보다 짧다.

     0                   1                   2                   3
    ┌───┬───┬───────┬───────────────┬───────────────────────────────┐
    │Ver│ T │  TKL  │     Code      │        Message ID (16)        │
    └───┴───┴───────┴───────────────┴───────────────────────────────┘
      2   2     4           8                      16                  = 32비트

    Ver  항상 1
    T    메시지 종류. 0=CON(확인 받겠다) 1=NON(안 받겠다) 2=ACK 3=RST
    TKL  토큰 길이. 요청과 응답을 짝지을 때 쓴다
    Code 상위 3비트가 부류, 하위 5비트가 세부. 0.01=GET, 2.05=Content

TCP가 없으니 재전송도 CoAP가 직접 한다. CON으로 보내면 상대가 ACK를 줄 때까지
2초, 4초, 8초… 로 늘려 가며 최대 4번 다시 보낸다. NON으로 보내면 한 번 보내고 만다.
TCP가 해 주던 일을 애플리케이션 계층이 떠안은 모습이다.
"""

import struct

VERSION = 1
TYPE_CON, TYPE_NON, TYPE_ACK, TYPE_RST = 0, 1, 2, 3
TYPE_NAMES = {0: "CON", 1: "NON", 2: "ACK", 3: "RST"}

# 코드는 부류.세부 꼴로 읽는다. (부류 << 5) | 세부
CODE_EMPTY = 0
CODE_GET, CODE_POST, CODE_PUT, CODE_DELETE = 1, 2, 3, 4
CODE_CREATED = (2 << 5) | 1     # 2.01
CODE_CHANGED = (2 << 5) | 4     # 2.04
CODE_CONTENT = (2 << 5) | 5     # 2.05
CODE_BAD_REQUEST = (4 << 5) | 0  # 4.00
CODE_NOT_FOUND = (4 << 5) | 4   # 4.04
CODE_METHOD_NOT_ALLOWED = (4 << 5) | 5  # 4.05

OPT_OBSERVE = 6
OPT_URI_PATH = 11
OPT_CONTENT_FORMAT = 12

CONTENT_TEXT, CONTENT_JSON = 0, 50

MAX_RETRANSMIT = 4      # RFC 7252가 정한 기본값
ACK_TIMEOUT = 2.0       # 첫 재전송까지 기다리는 초


def code_name(code):
    """69를 '2.05'처럼 읽기 쉬운 꼴로 바꾼다."""
    if code == 0:
        return "0.00(빈 메시지)"
    names = {CODE_GET: "0.01 GET", CODE_POST: "0.02 POST", CODE_PUT: "0.03 PUT",
             CODE_DELETE: "0.04 DELETE", CODE_CREATED: "2.01 Created",
             CODE_CHANGED: "2.04 Changed", CODE_CONTENT: "2.05 Content",
             CODE_BAD_REQUEST: "4.00 Bad Request", CODE_NOT_FOUND: "4.04 Not Found",
             CODE_METHOD_NOT_ALLOWED: "4.05 Method Not Allowed"}
    return names.get(code, f"{code >> 5}.{code & 0x1F:02d}")


def _encode_option_value(number_delta, value):
    """옵션 하나를 적는다. 델타와 길이를 4비트씩 쓰고, 12를 넘으면 뒤에 더 붙인다."""
    def split(n):
        if n < 13:
            return n, b""
        if n < 269:
            return 13, bytes([n - 13])
        return 14, struct.pack("!H", n - 269)

    d_nibble, d_ext = split(number_delta)
    l_nibble, l_ext = split(len(value))
    return bytes([(d_nibble << 4) | l_nibble]) + d_ext + l_ext + value


def encode(msg_type, code, message_id, token=b"", options=None, payload=b""):
    """CoAP 메시지 한 개를 바이트로 만든다.

    options는 (번호, 값) 목록이다. 번호가 오름차순이어야 한다. 델타로 적기
    때문이다. 같은 번호를 여러 번 쓰면 델타 0으로 이어 적는다. 경로가
    /a/b 면 Uri-Path 옵션을 두 번 적는다.
    """
    header = struct.pack("!BBH", (VERSION << 6) | (msg_type << 4) | len(token),
                         code, message_id)
    out = header + token

    last = 0
    for number, value in sorted(options or [], key=lambda o: o[0]):
        if isinstance(value, str):
            value = value.encode()
        elif isinstance(value, int):
            value = b"" if value == 0 else value.to_bytes((value.bit_length() + 7) // 8, "big")
        out += _encode_option_value(number - last, value)
        last = number

    if payload:
        out += b"\xff" + payload   # 0xFF 한 바이트가 옵션과 본문의 경계다
    return out


def decode(data):
    """바이트를 읽어 사전으로 돌려준다."""
    if len(data) < 4:
        raise ValueError("CoAP 메시지는 최소 4바이트다")
    first, code, message_id = struct.unpack("!BBH", data[:4])
    version = first >> 6
    msg_type = (first >> 4) & 0x03
    tkl = first & 0x0F
    if version != VERSION:
        raise ValueError(f"모르는 버전이다: {version}")

    offset = 4
    token = data[offset:offset + tkl]
    offset += tkl

    options, number = [], 0
    while offset < len(data) and data[offset] != 0xFF:
        byte = data[offset]
        offset += 1
        delta, length = byte >> 4, byte & 0x0F
        for target in ("delta", "length"):
            nibble = delta if target == "delta" else length
            if nibble == 13:
                extra = data[offset]
                offset += 1
                value = extra + 13
            elif nibble == 14:
                value = struct.unpack("!H", data[offset:offset + 2])[0] + 269
                offset += 2
            elif nibble == 15:
                raise ValueError("잘못된 옵션이다")
            else:
                value = nibble
            if target == "delta":
                delta = value
            else:
                length = value
        number += delta
        options.append((number, data[offset:offset + length]))
        offset += length

    payload = b""
    if offset < len(data) and data[offset] == 0xFF:
        payload = data[offset + 1:]

    return {"type": msg_type, "type_name": TYPE_NAMES[msg_type], "code": code,
            "code_name": code_name(code), "mid": message_id, "token": token,
            "options": options, "payload": payload, "size": len(data)}


def path_of(options):
    """Uri-Path 옵션들을 모아 /a/b 꼴로 되돌린다."""
    parts = [value.decode("utf-8", "replace") for number, value in options if number == OPT_URI_PATH]
    return "/" + "/".join(parts) if parts else "/"


def path_options(path):
    """/a/b 를 Uri-Path 옵션 목록으로 바꾼다."""
    return [(OPT_URI_PATH, part) for part in path.strip("/").split("/") if part]
