#!/usr/bin/env python3
"""gRPC 클라이언트. 원격 호출이 그냥 함수 호출처럼 보인다.

    stub.Get(sensor_pb2.SensorId(id="living-room"))

HTTP도 JSON도 URL도 보이지 않는다. 그 아래에서는 HTTP/2 스트림이 열리고
protobuf 바이트가 오가지만 코드에는 드러나지 않는다. 이것이 RPC(원격 프로시저
호출)라는 이름의 뜻이다.

대신 값을 치른다. .proto 없이는 아무것도 못 한다. curl로 눌러 볼 수도 없고,
브라우저에서 바로 부를 수도 없다(grpc-web이 따로 필요하다).

    python3 client.py get
    python3 client.py set 25.5
    python3 client.py watch          # 서버가 밀어 주는 값을 받는다
    python3 client.py size           # protobuf와 JSON의 바이트를 견준다
    python3 client.py error          # 없는 센서를 불러 상태 코드를 본다
"""

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    import grpc
except ImportError:
    print("grpcio가 없다. pip install grpcio grpcio-tools 로 깐다.", file=sys.stderr)
    raise SystemExit(2)

import sensor_pb2  # noqa: E402
import sensor_pb2_grpc  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="gRPC 클라이언트")
    ap.add_argument("command", choices=["get", "set", "watch", "size", "error"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9400)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--id", help="size 에서만 쓴다. 이 id로 바꿔 재어 비율이 어떻게 달라지는지 본다")
    args = ap.parse_args()

    channel = grpc.insecure_channel(f"{args.host}:{args.port}")
    stub = sensor_pb2_grpc.SensorServiceStub(channel)
    sensor_id = sensor_pb2.SensorId(id="living-room")

    try:
        if args.command == "get":
            started = time.time()
            reading = stub.Get(sensor_id, timeout=5)
            print(f"Get() → {reading.temperature}{reading.unit} "
                  f"({(time.time() - started) * 1000:.1f}ms)")
            print(f"  돌아온 것은 문자열이 아니라 Reading 객체다: {type(reading).__name__}")
            print(f"  reading.temperature = {reading.temperature} (이미 float다. 파싱이 없다)")

        elif args.command == "set":
            if args.value is None:
                print("set에는 값이 필요하다.", file=sys.stderr)
                return 1
            reading = stub.Set(sensor_pb2.SetRequest(id="living-room",
                                                     temperature=float(args.value)), timeout=5)
            print(f"Set({args.value}) → {reading.temperature}{reading.unit}")

        elif args.command == "watch":
            print(f"Watch() 스트림을 연다. {args.count}건을 받으면 끝낸다.")
            print("다른 창에서 python3 client.py set 26.0 을 돌려 본다.\n")
            received = 0
            for reading in stub.Watch(sensor_id):
                received += 1
                print(f"[{received}] {reading.temperature}{reading.unit} (ts={reading.ts:.3f})")
                if received >= args.count:
                    break
            print("\n스트림 하나로 여러 건을 받았다. 요청은 한 번뿐이었다.")
            print("REST였다면 같은 수만큼 요청을 되풀이했을 것이다(폴링).")

        elif args.command == "error":
            try:
                stub.Get(sensor_pb2.SensorId(id="kitchen"), timeout=5)
            except grpc.RpcError as exc:
                print(f"상태 코드: {exc.code().name}")
                print(f"메시지   : {exc.details()}")
                print()
                print("HTTP의 404에 해당한다. 다만 숫자가 아니라 이름이다.")
                print("gRPC 상태 코드는 17개로 정해져 있다. 내가 새로 만들 수 없다.")

        elif args.command == "size":
            reading = stub.Get(sensor_id, timeout=5)
            if args.id is not None:
                # 서버는 living-room 하나만 들고 있다. 긴 id가 비율을 어떻게
                # 바꾸는지 보려면 받은 Reading의 id만 갈아 끼워 다시 잰다.
                reading = sensor_pb2.Reading(id=args.id, temperature=reading.temperature,
                                             unit=reading.unit, ts=reading.ts)
                print(f"id를 {len(args.id)}자로 바꿔 잰다\n")
            proto_bytes = reading.SerializeToString()
            as_json = json.dumps({"id": reading.id, "temperature": reading.temperature,
                                  "unit": reading.unit, "ts": reading.ts},
                                 separators=(",", ":")).encode()
            print("같은 값을 두 가지로 적어 본다\n")
            print(f"  protobuf {len(proto_bytes):>3}바이트: {proto_bytes!r}")
            print(f"  JSON     {len(as_json):>3}바이트: {as_json.decode()}")
            print()
            pct = (1 - len(proto_bytes) / len(as_json)) * 100
            # 1% 아래를 :.0f 로 찍으면 0.7%가 1%로 올라가 문서와 화면이 어긋난다.
            shown = f"{pct:.0f}" if pct >= 10 else f"{pct:.1f}"
            print(f"  protobuf가 {len(as_json) - len(proto_bytes)}바이트 적다 "
                  f"({shown}% 줄었다)")
            print("  까닭이 둘이다. 하나는 필드 이름을 싣지 않는 것이다. 'temperature'라는")
            print("  글자 대신 .proto 에 적힌 번호 2만 싣는다. 받는 쪽도 같은 .proto 를 갖고")
            print("  있어야 2가 temperature임을 안다. 그래서 사람이 읽을 수 없다.")
            print("  또 하나는 proto3가 기본값인 필드를 아예 싣지 않는 것이다. 온도가 정확히")
            print("  0.0도면 temperature 필드가 통째로 빠지고, 네 값이 모두 기본값이면")
            print("  protobuf는 0바이트가 된다. 그래서 줄어드는 비율은 값에 따라 달라진다.")
            print("  set 0.0 을 한 뒤 다시 size 를 돌려 비율이 어떻게 바뀌는지 본다.")
            print("  --id 로 긴 id를 넣어 보면 비율이 거꾸로 떨어진다. 아끼는 바이트는")
            print("  거의 그대로인데 전체가 커지기 때문이다.")
            print(f"  이번에 아낀 바이트: {len(as_json) - len(proto_bytes)}"
                  " (값에 따라 달라지는 숫자다)")
            print()
            print("  JSON은 눈으로 읽힌다. protobuf는 짧다. 맞바꾸는 관계다.")
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            print(f"서버에 닿지 못했다: {exc.details()}", file=sys.stderr)
            print("먼저 서버를 띄운다: python3 server.py", file=sys.stderr)
            return 1
        raise
    finally:
        channel.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
