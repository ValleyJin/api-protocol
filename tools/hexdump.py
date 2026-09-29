"""바이트를 사람이 읽을 수 있게 찍어 주는 도구.

패킷을 눈으로 뜯어볼 때 쓴다. 필드 경계를 색이 아니라 주석으로 표시하려면
`annotate`를 쓴다.
"""


def hexdump(data, offset=0, width=16):
    """고전적인 16진수 덤프를 문자열로 돌려준다."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart = hexpart.ljust(width * 3 - 1)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset + i:08x}  {hexpart}  |{text}|")
    return "\n".join(lines)


def annotate(data, fields):
    """필드 경계를 붙여 찍는다.

    fields는 (이름, 시작, 길이) 세 쌍의 목록이다. 헤더를 처음 배울 때
    어느 바이트가 어느 필드인지 눈으로 맞춰 보라고 만들었다.
    """
    lines = []
    for name, start, length in fields:
        raw = data[start:start + length]
        hexs = " ".join(f"{b:02x}" for b in raw)
        if length <= 4:
            value = int.from_bytes(raw, "big")
            lines.append(f"  [{start:3d}:{start + length:3d}] {name:<22} {hexs:<24} = {value}")
        else:
            lines.append(f"  [{start:3d}:{start + length:3d}] {name:<22} {hexs}")
    return "\n".join(lines)


def mac(raw):
    """6바이트를 aa:bb:cc:dd:ee:ff 꼴로 바꾼다."""
    return ":".join(f"{b:02x}" for b in raw)


def ipv4(raw):
    """4바이트를 점 찍은 십진수로 바꾼다."""
    return ".".join(str(b) for b in raw)
