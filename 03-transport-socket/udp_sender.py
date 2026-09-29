#!/usr/bin/env python3
"""소켓 API만으로 만든 UDP 송신기.

보내는 쪽에는 bind()가 없다. sendto()를 부르는 순간 커널이 남는 포트를
알아서 붙인다. 받는 쪽만 포트를 미리 잡아야 한다. 남이 찾아올 주소가
있어야 하기 때문이다.

수신기를 띄우지 않고 보내 봐도 오류가 안 난다. UDP는 상대가 있는지 확인하지
않고 그냥 내보내기 때문이다. --check 옵션으로 그 모습을 확인할 수 있다.

    python3 udp_sender.py 안녕
    python3 udp_sender.py --burst 100      # 100개를 몰아 보내 유실을 본다
    python3 udp_sender.py --check          # 받는 쪽이 없어도 오류가 안 나는 것을 본다
"""

import argparse
import socket
import time


def main():
    ap = argparse.ArgumentParser(description="UDP 송신기")
    ap.add_argument("message", nargs="?", default="hello over UDP")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--burst", type=int, default=0, help="이 개수만큼 몰아 보낸다")
    ap.add_argument("--check", action="store_true", help="받는 쪽 없이 보내 본다")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    if args.check:
        dead_port = 65432   # 아무도 안 듣고 있을 만한 포트
        sock.sendto(b"nobody is listening", (args.host, dead_port))
        print(f"[송신] 아무도 없는 {args.host}:{dead_port} 로 보냈다. 오류가 나지 않았다.")
        print("[송신] UDP는 상대가 있는지 확인하지 않는다. 보내고 잊는다.")
        print("[송신] TCP였다면 connect()에서 ConnectionRefusedError가 났을 것이다.")
        sock.close()
        return 0

    if args.burst:
        start = time.time()
        for i in range(args.burst):
            sock.sendto(f"{i:05d}".encode() + b" " + args.message.encode(), (args.host, args.port))
        elapsed = time.time() - start
        print(f"[송신] {args.burst}개를 {elapsed * 1000:.1f}ms 만에 몰아 보냈다.")
        print(f"[송신] 내 쪽 포트: {sock.getsockname()[1]} (bind 없이 커널이 붙여 주었다)")
        print("[송신] 수신기가 몇 개를 받았는지 세어 본다. 숫자가 비면 그것이 유실이다.")
    else:
        payload = args.message.encode()
        sock.sendto(payload, (args.host, args.port))
        print(f"[송신] {len(payload)}바이트 보냈다: {args.message!r}")
        print(f"[송신] 내 쪽 포트: {sock.getsockname()[1]} (bind 없이 커널이 붙여 주었다)")

    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
