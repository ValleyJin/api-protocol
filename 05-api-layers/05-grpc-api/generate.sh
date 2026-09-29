#!/usr/bin/env bash
# .proto 에서 파이썬 코드를 만들어 낸다. sensor_pb2.py 와 sensor_pb2_grpc.py 가 생긴다.
# 저장소에 결과물을 함께 넣어 두었으니 그냥 돌려도 되지만, .proto 를 고치면 다시 돌린다.
set -euo pipefail
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. sensor.proto
echo "만들었다: sensor_pb2.py, sensor_pb2_grpc.py"
