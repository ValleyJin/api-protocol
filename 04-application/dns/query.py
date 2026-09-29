#!/usr/bin/env python3
"""DNS 질의 패킷을 바이트로 직접 조립하고, 응답을 손으로 파싱한다.

DNS 메시지는 12바이트 헤더로 시작한다.

    ┌────────────────┬────────────────┐
    │    ID (16)     │   플래그 (16)  │
    ├────────────────┼────────────────┤
    │  QDCOUNT (16)  │  ANCOUNT (16)  │   질문 개수 / 답 개수
    ├────────────────┼────────────────┤
    │  NSCOUNT (16)  │  ARCOUNT (16)  │   권한 개수 / 추가 개수
    └────────────────┴────────────────┘

이름은 점으로 잇지 않고 '길이 + 글자'를 되풀이해 적는다.

    example.com  →  \\x07example\\x03com\\x00

같은 이름이 응답 안에 여러 번 나오면 두 번째부터는 앞의 위치를 가리키는
2바이트 포인터로 줄인다(맨 앞 두 비트가 11). 이것을 이름 압축이라고 한다.
아래 파서가 이것까지 다룬다. 파싱이 까다로운 진짜 이유가 여기 있다.

    python3 query.py example.com
    python3 query.py example.com --type AAAA --server 1.1.1.1
    python3 query.py org --type DNSKEY --dnssec --bufsize 512   # TC 비트를 세워 본다
"""

import argparse
import random
import socket
import struct
import sys
import time

TYPES = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "PTR": 12, "MX": 15,
         "TXT": 16, "AAAA": 28, "DNSKEY": 48, "ANY": 255, "OPT": 41}
TYPE_NAMES = {v: k for k, v in TYPES.items()}

RCODES = {0: "성공", 1: "형식 오류", 2: "서버 실패", 3: "그런 이름이 없다",
          4: "지원하지 않는다", 5: "거절"}


def encode_name(name: str) -> bytes:
    """example.com 을 \\x07example\\x03com\\x00 으로 바꾼다."""
    out = b""
    for label in name.rstrip(".").split("."):
        if len(label) > 63:
            raise ValueError(f"라벨이 63바이트를 넘는다: {label}")
        out += bytes([len(label)]) + label.encode("ascii")
    return out + b"\x00"


def decode_name(msg: bytes, offset: int):
    """이름을 읽는다. 압축 포인터를 만나면 그 자리로 건너뛴다.

    (읽은 이름, 다음에 읽을 위치)를 돌려준다. 포인터를 따라간 경우에도
    '다음에 읽을 위치'는 포인터 바로 뒤여야 한다. 그래서 jumped를 따로 센다.
    """
    labels, jumped, next_offset = [], False, offset
    seen = 0
    while True:
        if offset >= len(msg):
            break
        length = msg[offset]
        if length == 0:
            offset += 1
            if not jumped:
                next_offset = offset
            break
        if length & 0xC0 == 0xC0:          # 맨 앞 두 비트가 11이면 포인터다
            pointer = struct.unpack("!H", msg[offset:offset + 2])[0] & 0x3FFF
            if not jumped:
                next_offset = offset + 2
            offset, jumped = pointer, True
            seen += 1
            if seen > 20:                  # 포인터가 서로를 가리키는 고장난 응답 방어
                break
            continue
        labels.append(msg[offset + 1:offset + 1 + length].decode("ascii", "replace"))
        offset += 1 + length
        if not jumped:
            next_offset = offset
    return ".".join(labels), next_offset


def build_query(name, qtype=1, dnssec=False, bufsize=None):
    """질의 메시지 한 개를 바이트로 만든다."""
    ident = random.randint(0, 0xFFFF)
    # 플래그 0x0100 = 재귀 질의를 원한다(RD 비트). 리졸버에게 대신 물어봐 달라는 뜻이다.
    arcount = 1 if (dnssec or bufsize) else 0
    header = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, arcount)
    question = encode_name(name) + struct.pack("!HH", qtype, 1)   # 클래스 1 = IN(인터넷)

    extra = b""
    if arcount:
        # EDNS0. OPT 레코드 하나를 추가 구역에 넣어 "나는 UDP로 이만큼까지 받을 수 있다"고 알린다.
        # 이 값이 작으면 서버가 응답을 자르고 TC 비트를 세운다.
        udp_size = bufsize or 4096
        ttl = 0x00008000 if dnssec else 0    # DO 비트 = DNSSEC 자료도 달라
        extra = b"\x00" + struct.pack("!HHIH", TYPES["OPT"], udp_size, ttl, 0)
    return ident, header + question + extra


def parse_response(msg):
    """응답을 헤더, 질문, 답 목록으로 가른다."""
    ident, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", msg[:12])
    offset = 12
    questions = []
    for _ in range(qd):
        name, offset = decode_name(msg, offset)
        qtype, qclass = struct.unpack("!HH", msg[offset:offset + 4])
        offset += 4
        questions.append((name, qtype))

    answers = []
    for _ in range(an + ns + ar):
        if offset >= len(msg):
            break
        name, offset = decode_name(msg, offset)
        if offset + 10 > len(msg):
            break
        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", msg[offset:offset + 10])
        offset += 10
        rdata = msg[offset:offset + rdlen]
        offset += rdlen

        if rtype == 1 and rdlen == 4:
            value = socket.inet_ntoa(rdata)
        elif rtype == 28 and rdlen == 16:
            value = socket.inet_ntop(socket.AF_INET6, rdata)
        elif rtype in (2, 5, 12):
            value, _ = decode_name(msg, offset - rdlen)
        elif rtype == 16:
            value = rdata[1:1 + rdata[0]].decode("ascii", "replace") if rdata else ""
        else:
            value = f"<{rdlen}바이트>"
        answers.append({"name": name, "type": TYPE_NAMES.get(rtype, rtype),
                        "ttl": ttl, "value": value, "rdlen": rdlen})

    return {
        "id": ident,
        "qr": bool(flags & 0x8000),
        "aa": bool(flags & 0x0400),
        "tc": bool(flags & 0x0200),   # 잘렸다. TCP로 다시 물어야 한다는 신호
        "ra": bool(flags & 0x0080),
        "rcode": flags & 0x000F,
        "counts": (qd, an, ns, ar),
        "questions": questions,
        "answers": answers,
    }


def ask(server, port, packet, use_tcp=False, timeout=5):
    """UDP로 묻는다. use_tcp면 2바이트 길이를 앞에 붙여 TCP로 묻는다."""
    if use_tcp:
        with socket.create_connection((server, port), timeout) as sock:
            sock.sendall(struct.pack("!H", len(packet)) + packet)
            head = sock.recv(2)
            want = struct.unpack("!H", head)[0]
            buf = b""
            while len(buf) < want:
                chunk = sock.recv(want - len(buf))
                if not chunk:
                    break
                buf += chunk
            return buf
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (server, port))
        data, _ = sock.recvfrom(65535)
        return data
    finally:
        sock.close()


def main():
    ap = argparse.ArgumentParser(description="DNS 질의를 직접 만들어 보낸다")
    ap.add_argument("name")
    ap.add_argument("--type", default="A", help="A, AAAA, MX, TXT, NS, DNSKEY 등")
    ap.add_argument("--server", default="8.8.8.8")
    ap.add_argument("--port", type=int, default=53)
    ap.add_argument("--dnssec", action="store_true", help="DNSSEC 자료까지 달라고 한다")
    ap.add_argument("--bufsize", type=int, help="EDNS0로 알릴 UDP 수신 한계")
    args = ap.parse_args()

    qtype = TYPES.get(args.type.upper())
    if qtype is None:
        print(f"모르는 종류다: {args.type}. 쓸 수 있는 것: {', '.join(TYPES)}", file=sys.stderr)
        return 1

    ident, packet = build_query(args.name, qtype, args.dnssec, args.bufsize)
    print(f"질의 {len(packet)}바이트를 {args.server}:{args.port} 로 보낸다")
    print("  " + " ".join(f"{b:02x}" for b in packet))
    print(f"  헤더 12바이트 + 질문 {len(encode_name(args.name)) + 4}바이트"
          + (f" + EDNS0 11바이트" if args.dnssec or args.bufsize else ""))
    print()

    started = time.time()
    try:
        data = ask(args.server, args.port, packet)
    except socket.timeout:
        print("답이 없다. 서버 주소와 방화벽을 본다.", file=sys.stderr)
        return 1
    elapsed = (time.time() - started) * 1000

    result = parse_response(data)
    print(f"응답 {len(data)}바이트, {elapsed:.1f}ms")
    print(f"  ID 맞음: {result['id'] == ident}   결과: {RCODES.get(result['rcode'], result['rcode'])}")
    print(f"  질문 {result['counts'][0]} / 답 {result['counts'][1]} / "
          f"권한 {result['counts'][2]} / 추가 {result['counts'][3]}")

    if result["tc"]:
        print()
        print("  TC 비트가 서 있다. 응답이 UDP 한계를 넘어 잘렸다는 뜻이다.")
        print("  진짜 리졸버는 이때 TCP로 같은 질의를 다시 보낸다. 그대로 해 본다.")
        data = ask(args.server, args.port, packet, use_tcp=True)
        result = parse_response(data)
        print(f"  TCP로 다시 물었다: {len(data)}바이트, 답 {result['counts'][1]}개")
        print("  이것이 'DNS는 UDP를 쓴다'는 말이 반쪽인 이유다. TCP도 쓴다.")

    print()
    for rr in result["answers"]:
        print(f"  {rr['name']:<32} {rr['type']:<8} TTL {rr['ttl']:<7} {rr['value']}")

    if not result["answers"]:
        print("  답 구역이 비어 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
