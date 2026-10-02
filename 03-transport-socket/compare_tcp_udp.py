#!/usr/bin/env python3
"""TCP와 UDP에 같은 일을 시켜 다섯 가지를 나란히 잰다.

표로 읽는 것과 직접 재는 것은 다르다. "TCP는 순서를 지켜 주고 UDP는 안 지켜
준다"는 문장은 외우기 쉽지만, 그 차이가 코드에서 어떤 모습인지는 잘 안 와닿는다.
이 스크립트는 같은 메시지를 두 프로토콜로 보내고 아래 다섯을 잰다.

    1. 연결 비용      첫 바이트를 보내기까지 무엇이 오가야 하는가
    2. 메시지 경계    send를 세 번 하면 recv도 세 번인가
    3. 순서          보낸 순서대로 도착하는가
    4. 유실          받는 쪽이 못 따라가면 어떻게 되는가
    5. 처리량        같은 건수를 나르는 데 얼마나 걸리는가

서버는 이 스크립트가 스레드로 직접 띄운다. 다른 창을 열지 않아도 된다.

    python3 compare_tcp_udp.py
    python3 compare_tcp_udp.py --count 5000
"""

import argparse
import socket
import struct
import threading
import time


# ── 서버 둘을 스레드로 띄운다 ────────────────────────────────────────
def tcp_echo_server(sock, stop):
    """받은 것을 그대로 돌려보낸다. 한 번에 한 연결만 다룬다."""
    sock.settimeout(0.5)
    while not stop.is_set():
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        with conn:
            conn.settimeout(5)
            while not stop.is_set():
                try:
                    data = conn.recv(65535)
                except (socket.timeout, OSError):
                    break
                if not data:
                    break
                try:
                    conn.sendall(data)
                except OSError:
                    break


def udp_echo_server(sock, stop):
    sock.settimeout(0.5)
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            sock.sendto(data, addr)
        except OSError:
            break


# ── 1. 연결 비용 ─────────────────────────────────────────────────────
def measure_connect_cost(tcp_port, udp_port):
    """첫 메시지 한 건을 주고받는 데 걸린 시간을 잰다.

    TCP는 그 안에 3-way handshake가 들어 있다. UDP는 없다. 루프백이라 차이가
    작게 나오지만, 지연이 큰 망에서는 왕복 한 번이 그대로 더 붙는다.
    """
    payload = b"hello"

    started = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(("127.0.0.1", tcp_port))     # 여기서 SYN → SYN-ACK → ACK
        s.sendall(payload)
        s.recv(1024)
    tcp_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(5)
        s.sendto(payload, ("127.0.0.1", udp_port))   # 맺을 연결이 없다
        s.recvfrom(1024)
    udp_ms = (time.perf_counter() - started) * 1000

    return {
        "TCP": f"{tcp_ms:.2f}ms (핸드셰이크 포함)",
        "UDP": f"{udp_ms:.2f}ms (핸드셰이크 없음)",
        "뜻": "TCP는 데이터를 보내기 전에 왕복 한 번을 먼저 쓴다",
    }


# ── 2. 메시지 경계 ───────────────────────────────────────────────────
def measure_boundary(tcp_port, udp_port):
    """send를 세 번 하고 recv가 몇 번에 나뉘어 오는지 센다."""
    pieces = [b"first", b"second", b"third"]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(("127.0.0.1", tcp_port))
        for piece in pieces:
            s.sendall(piece)
            time.sleep(0.02)       # 띄워 보내도 결과는 같다
        time.sleep(0.2)
        tcp_first = s.recv(65535)
    tcp_calls = 1 if tcp_first == b"".join(pieces) else -1

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1)
        for piece in pieces:
            s.sendto(piece, ("127.0.0.1", udp_port))
        udp_got = []
        for _ in pieces:
            try:
                udp_got.append(s.recvfrom(65535)[0])
            except socket.timeout:
                break

    return {
        "TCP": (f"send 3번 → recv 1번에 {len(tcp_first)}바이트가 붙어서 왔다"
                if tcp_calls == 1 else f"recv로 {len(tcp_first)}바이트를 받았다"),
        "UDP": f"sendto 3번 → recvfrom {len(udp_got)}번, 각각 {[len(x) for x in udp_got]}바이트",
        "뜻": "TCP는 바이트 흐름이라 경계가 없다. UDP는 보낸 덩어리가 그대로 하나씩 온다",
    }


# ── 3. 순서 ──────────────────────────────────────────────────────────
def measure_order(tcp_port, udp_port, count):
    """1부터 세어 보내고 도착 순서를 본다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(("127.0.0.1", tcp_port))
        for i in range(count):
            s.sendall(struct.pack("!I", i))
        buf = b""
        while len(buf) < count * 4:
            chunk = s.recv(65535)
            if not chunk:
                break
            buf += chunk
    tcp_seq = [struct.unpack("!I", buf[i:i + 4])[0] for i in range(0, len(buf) - 3, 4)]
    tcp_ok = tcp_seq == list(range(count))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1)
        for i in range(count):
            s.sendto(struct.pack("!I", i), ("127.0.0.1", udp_port))
        udp_seq = []
        while True:
            try:
                udp_seq.append(struct.unpack("!I", s.recvfrom(65535)[0])[0])
            except socket.timeout:
                break
    udp_ok = udp_seq == list(range(len(udp_seq)))

    return {
        "TCP": f"{len(tcp_seq)}개 도착, 순서 그대로: {tcp_ok}",
        "UDP": f"{len(udp_seq)}개 도착, 순서 그대로: {udp_ok}",
        "뜻": ("루프백에서는 UDP도 순서가 지켜지는 일이 많다. 지켜 준다는 보장이 없을 뿐이다. "
               "일부러 뒤섞으려면 netem이나 dnctl을 쓴다"),
    }


# ── 4. 유실 ──────────────────────────────────────────────────────────
def measure_loss(count, payload_size=200):
    """받는 쪽 버퍼를 작게 줄이고 몰아 보내 무슨 일이 생기는지 본다.

    루프백은 선이 깨끗해서 저절로는 유실이 안 난다. 그래서 커널 버퍼를
    일부러 좁혀 넘치게 만든다. 실제 망에서 혼잡이 났을 때와 같은 일이다.
    """
    body = b"x" * payload_size

    # UDP: 버퍼가 넘치면 커널이 그냥 버린다. 아무도 모른다.
    r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
    r.bind(("127.0.0.1", 0))
    udp_port = r.getsockname()[1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(count):
        s.sendto(struct.pack("!I", i) + body, ("127.0.0.1", udp_port))
    s.close()
    time.sleep(0.3)
    r.setblocking(False)
    udp_got = 0
    while True:
        try:
            r.recv(65535)
            udp_got += 1
        except BlockingIOError:
            break
    r.close()

    # TCP: 버퍼가 차면 보내는 쪽이 멈춰 선다. 버리지 않는다.
    #
    # 여기서 운영체제가 끼어든다. listener에 SO_RCVBUF를 2048로 걸어도 macOS는
    # accept된 소켓의 수신 버퍼를 제 판단으로 키운다(이 기기에서 326640바이트).
    # 그래서 보내는 쪽의 SO_SNDBUF도 함께 줄여야 금세 꽉 찬다.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
    listener.bind(("127.0.0.1", 0))
    tcp_port = listener.getsockname()[1]
    listener.listen(1)

    sender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2048)
    sender.settimeout(5)
    sender.connect(("127.0.0.1", tcp_port))
    conn, _ = listener.accept()           # 받아 두고 읽지는 않는다
    recv_buf = conn.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

    sender.setblocking(False)
    sent = 0
    blocked = False
    for i in range(count):
        try:
            sender.sendall(struct.pack("!I", i) + body)
            sent += 1
        except BlockingIOError:
            blocked = True                # 더 못 보낸다. 여기서 멈춰 선다
            break
        except OSError:
            break

    sender.close()
    conn.close()
    listener.close()

    return {
        "TCP": (f"{sent}건({sent * (payload_size + 4)}바이트)을 보낸 뒤 더 못 보내고 멈춰 섰다. "
                f"한 건도 버리지 않았다" if blocked
                else f"{sent}건을 모두 보냈다 (버퍼가 그만큼 컸다. 수신 버퍼 {recv_buf}바이트)"),
        "UDP": f"{count}건을 다 보냈지만 {udp_got}건만 도착했다 "
               f"({(count - udp_got) / count * 100:.1f}% 사라졌다)",
        "뜻": "TCP는 받는 쪽이 못 따라가면 보내는 쪽을 멈춰 세운다. UDP는 그냥 버린다",
    }


# ── 5. 처리량 ────────────────────────────────────────────────────────
def measure_throughput(tcp_port, udp_port, count):
    """같은 건수를 왕복시키는 데 걸린 시간을 잰다."""
    body = b"x" * 100

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.connect(("127.0.0.1", tcp_port))
        started = time.perf_counter()
        for _ in range(count):
            s.sendall(body)
            got = b""
            while len(got) < len(body):
                got += s.recv(65535)
        tcp_sec = time.perf_counter() - started

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(2)
        started = time.perf_counter()
        done = 0
        for _ in range(count):
            s.sendto(body, ("127.0.0.1", udp_port))
            try:
                s.recvfrom(65535)
                done += 1
            except socket.timeout:
                break
        udp_sec = time.perf_counter() - started

    return {
        "TCP": f"{count}회 왕복 {tcp_sec * 1000:.0f}ms, 초당 {count / tcp_sec:.0f}회",
        "UDP": f"{done}회 왕복 {udp_sec * 1000:.0f}ms, 초당 {done / udp_sec:.0f}회",
        "뜻": "연결 하나를 계속 쓰면 둘의 차이가 크지 않다. 차이는 보장에서 온다",
    }


def main():
    ap = argparse.ArgumentParser(description="TCP와 UDP를 나란히 재어 견준다")
    ap.add_argument("--count", type=int, default=2000, help="유실 실험에 몰아 보낼 건수 (기본 2000)")
    ap.add_argument("--rounds", type=int, default=200, help="처리량 실험 왕복 횟수 (기본 200)")
    args = ap.parse_args()

    # 서버 둘을 띄운다
    tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_listener.bind(("127.0.0.1", 0))
    tcp_listener.listen(8)
    tcp_port = tcp_listener.getsockname()[1]

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", 0))
    udp_port = udp_sock.getsockname()[1]

    stop = threading.Event()
    threading.Thread(target=tcp_echo_server, args=(tcp_listener, stop), daemon=True).start()
    threading.Thread(target=udp_echo_server, args=(udp_sock, stop), daemon=True).start()
    time.sleep(0.2)

    print(f"에코 서버를 띄웠다. TCP {tcp_port}, UDP {udp_port}")
    print("같은 일을 두 프로토콜로 시켜 다섯 가지를 잰다.\n")

    tests = [
        ("1. 연결 비용", lambda: measure_connect_cost(tcp_port, udp_port)),
        ("2. 메시지 경계", lambda: measure_boundary(tcp_port, udp_port)),
        ("3. 순서", lambda: measure_order(tcp_port, udp_port, 50)),
        ("4. 유실", lambda: measure_loss(args.count)),
        ("5. 처리량", lambda: measure_throughput(tcp_port, udp_port, args.rounds)),
    ]

    for title, fn in tests:
        print("=" * 74)
        print(title)
        print("=" * 74)
        try:
            result = fn()
        except Exception as exc:
            print(f"  재지 못했다: {type(exc).__name__}: {exc}\n")
            continue
        print(f"  TCP : {result['TCP']}")
        print(f"  UDP : {result['UDP']}")
        print(f"  뜻  : {result['뜻']}")
        print()

    stop.set()
    time.sleep(0.3)
    try:
        tcp_listener.close()
        udp_sock.close()
    except OSError:
        pass

    print("=" * 74)
    print("정리")
    print("=" * 74)
    print("  TCP가 더 주는 것: 연결, 도착 보장, 순서 보장, 흐름 조절")
    print("  그 값으로 내는 것: 왕복 한 번(핸드셰이크), 헤더 20~36바이트, 상태 관리")
    print("  UDP가 주는 것  : 헤더 8바이트, 핸드셰이크 없음, 보낸 덩어리가 그대로 온다")
    print("  그 대가       : 사라져도 모른다, 순서도 모른다, 혼잡 조절도 내 몫")
    print()
    print("  그래서 이렇게 갈린다")
    print("    받아야 할 것을 다 받아야 한다        → TCP (HTTP, MQTT)")
    print("    한 통에 담기고 늦으면 버려도 된다    → UDP (DNS, 영상 통화)")
    print("    UDP를 쓰되 보장이 필요하다           → 애플리케이션이 직접 만든다")
    print()
    print("  마지막 줄이 CoAP가 한 선택이다. 04-application/coap 에서 재전송을")
    print("  손으로 적는 것이 바로 이 대가를 치르는 모습이다.")
    print("  DNS가 UDP를 고르고도 응답이 커지면 TCP로 넘어가는 까닭도 여기 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
