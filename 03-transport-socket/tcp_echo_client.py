#!/usr/bin/env python3
"""소켓 API만으로 만든 TCP 에코 클라이언트.

서버와 호출 순서가 다르다. 클라이언트는 남이 찾아오기를 기다리지 않으니
bind()와 listen(), accept()가 없다.

    socket()   창구를 만든다
    connect()  상대 주소로 3-way handshake를 건다. 여기서 SYN이 나간다
    send()     바이트를 보낸다
    recv()     답을 읽는다
    close()    FIN을 보내 연결을 닫는다

bind()를 부르지 않아도 된다. 커널이 남는 포트를 알아서 하나 골라 붙인다.
그 포트를 임시 포트(ephemeral port)라고 한다. 아래에서 직접 찍어 본다.

여기서 꼭 짚을 것이 하나 있다. TCP는 바이트 흐름이다. 메시지 경계를 지켜
주지 않는다. send()를 세 번 했다고 recv()가 세 번 나뉘어 오지 않는다.
--stream 옵션으로 그 모습을 직접 만들어 볼 수 있다.

    python3 tcp_echo_client.py 안녕
    python3 tcp_echo_client.py --stream
"""

import argparse
import socket
import sys
import time


def send_once(host, port, message):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect((host, port))   # 여기서 SYN → SYN-ACK → ACK 가 오간다
        local = sock.getsockname()
        print(f"[클라] 연결됐다. 내 쪽 주소는 {local[0]}:{local[1]} 이다.")
        print(f"[클라] 포트 {local[1]} 은 내가 고른 것이 아니라 커널이 붙인 임시 포트다.")

        payload = message.encode()
        sock.sendall(payload)
        print(f"[클라] {len(payload)}바이트 보냈다: {message!r}")

        echoed = sock.recv(4096)
        print(f"[클라] {len(echoed)}바이트 돌아왔다: {echoed.decode(errors='replace')!r}")
        print(f"[클라] 보낸 것과 같은가: {echoed == payload}")


def send_stream(host, port):
    """작은 조각을 여러 번 보내고 한 번에 읽어, 경계가 사라지는 것을 본다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect((host, port))
        pieces = [b"first", b"second", b"third"]
        for piece in pieces:
            sock.sendall(piece)
            print(f"[클라] send() 호출: {piece!r}")
            time.sleep(0.05)   # 조금 띄워 보내도 결과는 같다

        time.sleep(0.3)
        received = sock.recv(4096)
        print(f"\n[클라] recv() 한 번에 받은 것: {received!r}")
        print(f"[클라] send()를 {len(pieces)}번 했는데 recv()는 한 번에 {len(received)}바이트를 받았다.")
        print("[클라] TCP는 바이트 흐름이라 메시지 경계를 지켜 주지 않는다.")
        print("[클라] 경계가 필요하면 길이를 앞에 붙이거나 줄바꿈 같은 구분자를 직접 정해야 한다.")
        print("[클라] 04 폴더의 HTTP, MQTT가 각자 이 문제를 어떻게 푸는지 견줘 보면 좋다.")


def main():
    ap = argparse.ArgumentParser(description="소켓 API만으로 만든 TCP 클라이언트")
    ap.add_argument("message", nargs="?", default="hello from socket API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--stream", action="store_true", help="바이트 흐름의 성질을 보여 준다")
    args = ap.parse_args()

    try:
        if args.stream:
            send_stream(args.host, args.port)
        else:
            send_once(args.host, args.port, args.message)
    except ConnectionRefusedError:
        print(f"연결이 거절됐다. {args.host}:{args.port} 에 서버가 떠 있는지 본다.", file=sys.stderr)
        print("  python3 tcp_echo_server.py", file=sys.stderr)
        return 1
    except socket.timeout:
        print("시간이 다 됐다. 서버가 답하지 않는다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
