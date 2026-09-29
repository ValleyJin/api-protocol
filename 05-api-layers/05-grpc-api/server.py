#!/usr/bin/env python3
"""gRPC 서버. .proto 가 정한 계약을 구현하기만 하면 된다.

앞의 여섯 가지와 결정적으로 다른 점은 **내가 규약을 적지 않는다**는 것이다.
sensor.proto 가 메시지 모양과 메서드 이름을 정하고, 그 파일에서 만들어진
코드가 직렬화와 HTTP/2 프레이밍을 모두 맡는다. 나는 함수 몸통만 채운다.

    01-socket-api  줄바꿈, OK/ERR, 값 뽑기를 모두 내가 적었다
    03-rest-api    HTTP가 메서드와 상태 코드를 정해 주었다. 본문 모양은 내 몫
    05-grpc-api    본문 모양까지 .proto 가 정한다. 나는 함수만 채운다

Watch는 서버 스트리밍이다. 04-application/websocket 에서 프레임을 손으로
만들며 했던 일을, 여기서는 yield 한 줄로 한다.

    ./generate.sh     # sensor.proto 를 고쳤을 때만
    python3 server.py
"""

import argparse
import pathlib
import sys
import time
from concurrent import futures

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

try:
    import grpc
except ImportError:
    print("grpcio가 없다. pip install grpcio grpcio-tools 로 깐다.", file=sys.stderr)
    raise SystemExit(2)

import sensor_pb2  # noqa: E402
import sensor_pb2_grpc  # noqa: E402
from common.store import get, set_value  # noqa: E402


def to_reading(record):
    """저장소의 사전을 protobuf 메시지로 옮긴다."""
    return sensor_pb2.Reading(id=record["sensor"], temperature=record["temperature"],
                              unit=record["unit"], ts=record["ts"])


class SensorService(sensor_pb2_grpc.SensorServiceServicer):
    def __init__(self, verbose=True):
        self.verbose = verbose

    def Get(self, request, context):
        if self.verbose:
            print(f"[서버] Get(id={request.id!r})", flush=True)
        if request.id != "living-room":
            # 상태 코드도 .proto 바깥에 이미 정해져 있다. HTTP의 404에 해당한다.
            context.abort(grpc.StatusCode.NOT_FOUND, f"그런 센서가 없다: {request.id}")
        return to_reading(get())

    def Set(self, request, context):
        if self.verbose:
            print(f"[서버] Set(id={request.id!r}, temperature={request.temperature})", flush=True)
        if request.id != "living-room":
            context.abort(grpc.StatusCode.NOT_FOUND, f"그런 센서가 없다: {request.id}")
        return to_reading(set_value(request.temperature))

    def Watch(self, request, context):
        """서버 스트리밍. yield 할 때마다 클라이언트에게 한 건이 간다."""
        if self.verbose:
            print(f"[서버] Watch(id={request.id!r}) 스트림을 연다", flush=True)
        last = None
        try:
            while context.is_active():
                record = get()
                if record["ts"] != last:
                    last = record["ts"]
                    yield to_reading(record)
                time.sleep(0.5)
        finally:
            if self.verbose:
                print("[서버] Watch 스트림을 닫는다", flush=True)


def main():
    ap = argparse.ArgumentParser(description="gRPC 센서 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9400)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    sensor_pb2_grpc.add_SensorServiceServicer_to_server(SensorService(not args.quiet), server)
    server.add_insecure_port(f"{args.host}:{args.port}")
    server.start()
    print(f"[서버] grpc://{args.host}:{args.port} — HTTP/2 위에서 돈다", flush=True)
    print("[서버] 메서드: Get, Set, Watch(스트리밍). 멈추려면 Ctrl+C", flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
        server.stop(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
