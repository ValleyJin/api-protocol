#!/usr/bin/env python3
"""소켓 API만으로 만든 TCP 에코 서버.

라이브러리를 쓰지 않는다. 운영체제가 내주는 소켓 함수만으로 서버를 세운다.
호출 순서가 곧 TCP가 연결을 맺는 순서와 맞물린다.

    socket()   랜카드가 아니라 커널에 "통신 창구를 하나 달라"고 한다
    bind()     그 창구에 포트 번호를 붙인다. 이제 남이 찾아올 주소가 생겼다
    listen()   "이 창구로 들어오는 연결 요청을 받겠다"고 커널에 알린다
      ↓        여기서부터 커널이 3-way handshake를 대신 처리한다
    accept()   handshake가 끝난 연결을 하나 꺼내 온다. 새 소켓이 생긴다
    recv()     상대가 보낸 바이트를 읽는다
    send()     바이트를 돌려보낸다
    close()    4-way close로 연결을 닫는다

accept()가 돌려주는 소켓은 처음 만든 소켓과 다른 물건이다. 처음 것은 계속
문 앞에서 손님을 받고, 새 것이 그 손님 한 명과 이야기한다.

    python3 tcp_echo_server.py
    python3 tcp_echo_server.py --host 0.0.0.0 --port 9000
"""

import argparse
import socket
import sys

BUFFER = 4096


def serve(host, port, once=False):
    # AF_INET = IPv4, SOCK_STREAM = TCP. 이 두 값이 전송 계층을 고른다.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # 이 줄이 없으면 서버를 껐다 켤 때 "Address already in use"가 난다.
    # 방금 닫은 연결이 TIME_WAIT 상태로 포트를 쥐고 있기 때문이다.
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server.bind((host, port))
    server.listen(5)   # 5는 아직 accept하지 않은 연결을 몇 개까지 쌓아 둘지다
    print(f"[서버] {host}:{port} 에서 기다린다. 멈추려면 Ctrl+C")
    print(f"[서버] 지금 상태는 LISTEN이다. 다른 창에서 확인해 본다:")
    print(f"       netstat -an | grep {port}          (리눅스는 ss -tan)")

    try:
        while True:
            # accept()는 연결이 올 때까지 여기서 멈춘다.
            # 돌아올 때는 handshake가 이미 끝나 있다.
            conn, addr = server.accept()
            print(f"\n[서버] {addr[0]}:{addr[1]} 에서 연결됐다. 상태는 ESTABLISHED다.")
            with conn:
                while True:
                    data = conn.recv(BUFFER)
                    if not data:
                        # 빈 바이트는 "상대가 FIN을 보냈다"는 뜻이다.
                        # 오류가 아니라 정상적인 연결 종료 신호다.
                        print(f"[서버] {addr[0]}:{addr[1]} 가 연결을 닫았다 (FIN을 받았다).")
                        break
                    print(f"[서버] {len(data)}바이트 받았다: {data[:60]!r}")
                    conn.sendall(data)   # 받은 그대로 돌려보낸다
            if once:
                break
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.close()


def main():
    ap = argparse.ArgumentParser(description="소켓 API만으로 만든 TCP 에코 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--once", action="store_true", help="연결 하나만 받고 끝낸다")
    args = ap.parse_args()
    serve(args.host, args.port, args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
