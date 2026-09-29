#!/usr/bin/env python3
"""같은 에코 서버를 select()로 다시 짠다. 한 스레드로 여러 연결을 받는다.

tcp_echo_server.py는 한 번에 한 연결만 다룬다. accept()로 받은 손님과
이야기가 끝나야 다음 손님을 받는다. 둘째 클라이언트를 붙여 보면 바로 보인다.

select()는 "이 소켓들 가운데 지금 읽을 것이 있는 소켓을 알려 달라"고 커널에
묻는 함수다. 답이 올 때까지 멈춰 있다가, 준비된 소켓만 골라 돌려준다. 그래서
스레드 하나로 연결 수십 개를 돌릴 수 있다.

이것이 05 폴더에서 다루는 "계층을 올리면 무엇이 감춰지는가"의 첫 사례다.
asyncio나 웹 프레임워크는 이 select() 되풀이를 안쪽에 감춰 둔 것이다.

    python3 tcp_select_server.py
    # 다른 창 두 개에서 동시에
    python3 tcp_echo_client.py --port 9000
"""

import argparse
import select
import socket

BUFFER = 4096


def main():
    ap = argparse.ArgumentParser(description="select()로 여러 연결을 받는 에코 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(16)
    print(f"[서버] {args.host}:{args.port} — select()로 여러 연결을 한꺼번에 받는다.")

    # 지켜볼 소켓 목록. 처음에는 손님을 받는 소켓 하나뿐이다.
    watching = [listener]
    names = {}

    try:
        while True:
            # 읽을 것이 생긴 소켓만 골라 돌려준다. 아무것도 없으면 여기서 멈춰 기다린다.
            readable, _, _ = select.select(watching, [], [], 1.0)

            for sock in readable:
                if sock is listener:
                    # 손님을 받는 소켓이 준비됐다는 것은 새 연결이 왔다는 뜻이다.
                    conn, addr = listener.accept()
                    conn.setblocking(False)
                    watching.append(conn)
                    names[conn] = f"{addr[0]}:{addr[1]}"
                    print(f"[서버] {names[conn]} 붙었다. 지금 연결 {len(watching) - 1}개")
                    continue

                # 그 밖의 소켓이 준비됐다는 것은 데이터가 왔거나 상대가 닫았다는 뜻이다.
                try:
                    data = sock.recv(BUFFER)
                except ConnectionResetError:
                    data = b""

                if not data:
                    print(f"[서버] {names.get(sock, '?')} 닫혔다. 남은 연결 {len(watching) - 2}개")
                    watching.remove(sock)
                    names.pop(sock, None)
                    sock.close()
                    continue

                print(f"[서버] {names.get(sock, '?')} 에서 {len(data)}바이트 — 되돌려 보낸다")
                sock.sendall(data)
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        for sock in watching:
            sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
