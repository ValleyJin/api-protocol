#!/usr/bin/env python3
"""SDK를 써 본다. 그리고 SDK가 감춘 것을 열어 본다.

    python3 ../03-rest-api/server.py &
    python3 demo.py
    python3 demo.py --trace        # SDK 안에서 무슨 일을 하는지 본다
    python3 demo.py --fail         # 서버가 없을 때 어떻게 되는지 본다
"""

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sensor_sdk import (Reading, SensorClient, SensorNotFound,  # noqa: E402
                        SensorRejected, SensorUnavailable, VERSION)


def main():
    ap = argparse.ArgumentParser(description="SDK 계층 시연")
    ap.add_argument("--base", default="http://127.0.0.1:9200")
    ap.add_argument("--trace", action="store_true", help="SDK 안을 들여다본다")
    ap.add_argument("--fail", action="store_true", help="없는 서버를 불러 본다")
    args = ap.parse_args()

    base = "http://127.0.0.1:9999" if args.fail else args.base

    print(f"sensor-sdk {VERSION}\n")
    print("=" * 66)
    print("쓰는 쪽 코드는 이것이 전부다")
    print("=" * 66)
    print("    with SensorClient() as client:")
    print("        reading = client.get()")
    print("        print(reading.temperature)")
    print()

    with SensorClient(base, trace=args.trace) as client:
        if args.fail:
            print("=" * 66)
            print("서버가 없을 때")
            print("=" * 66)
            started = time.time()
            try:
                client.get()
            except SensorUnavailable as exc:
                elapsed = time.time() - started
                print(f"  SensorUnavailable: {exc}")
                print(f"  {elapsed:.1f}초 동안 {client.request_count}번 해 보고 포기했다.")
                print()
                print("  SDK가 없었다면 이 재시도를 쓰는 쪽이 적어야 했다.")
                print("  --trace 를 붙이면 언제 얼마나 기다렸는지 보인다.")
            return 0

        try:
            print("=" * 66)
            print("1. 값 읽기")
            print("=" * 66)
            reading = client.get()
            print(f"  client.get() → {reading}")
            print(f"  돌아온 것의 타입: {type(reading).__name__}")
            print(f"  reading.temperature 는 {type(reading.temperature).__name__} 이다. "
                  "문자열을 숫자로 바꾸는 코드가 없다.")
            try:
                reading.temperature = 0     # 얼려 둔 자료라 막힌다
                print("  값을 바꿀 수 있다 (그러면 안 되는데)")
            except Exception as exc:
                print(f"  reading.temperature = 0 → {type(exc).__name__}")
                print("  얼려 둔 자료라 실수로 고쳐 쓸 수 없다. 사전이었다면 그냥 바뀐다.")
            print()

            print("=" * 66)
            print("2. 값 올리기")
            print("=" * 66)
            updated = client.set(24.5)
            print(f"  client.set(24.5) → {updated}")
            print()

            print("=" * 66)
            print("3. 오류가 내 언어의 예외로 바뀐다")
            print("=" * 66)
            try:
                client.get("kitchen")
            except SensorNotFound as exc:
                print(f"  client.get('kitchen') → SensorNotFound: {exc}")
                print("  HTTP 404 라는 숫자를 쓰는 쪽이 알 필요가 없다.")
            try:
                client.set("스물넷")
            except (SensorRejected, TypeError, ValueError) as exc:
                print(f"  client.set('스물넷') → {type(exc).__name__}: {exc}")
            print()

            print("=" * 66)
            print("4. 이 짧은 코드가 실제로 부른 횟수")
            print("=" * 66)
            print(f"  HTTP 요청 {client.request_count}번")
            print("  쓰는 쪽 코드에는 요청이라는 말이 한 번도 안 나왔다.")
            print("  이것이 SDK의 값이자 대가다. 편하지만 무슨 일이 나는지 안 보인다.")
            print("  느려질 때 SDK 안을 열지 않고는 까닭을 알 수 없다. --trace 가 그래서 있다.")
        except SensorUnavailable as exc:
            print(f"\n서버에 닿지 못했다: {exc}", file=sys.stderr)
            print("먼저 REST 서버를 띄운다: python3 ../03-rest-api/server.py", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
