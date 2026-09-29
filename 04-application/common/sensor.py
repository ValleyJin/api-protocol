"""다섯 폴더가 함께 쓰는 공통 과제.

프로토콜끼리 견주려면 같은 일을 시켜야 한다. 이 파일이 그 '같은 일'을 정한다.

    센서 값 하나를 올린다. 받는 쪽이 그 값을 읽는다.

값의 모양을 여기서 한 번만 정해 두고 HTTP, WebSocket, MQTT, CoAP가 모두
이것을 쓴다. 그래야 "메시지 한 건이 몇 바이트인가"를 나란히 놓고 볼 수 있다.

DNS는 이 과제에서 뺀다. 이름을 푸는 프로토콜이라 값을 올리는 쪽이 없다.
"""

import json
import random
import time

SENSOR_ID = "living-room"
TOPIC = "home/living-room/temperature"   # MQTT가 쓰는 주제
PATH = "/sensors/living-room/temperature"  # HTTP와 CoAP가 쓰는 경로


def reading(value=None, sensor=SENSOR_ID):
    """센서 값 한 건을 만든다. 값을 주지 않으면 그럴듯한 값을 지어낸다."""
    return {
        "sensor": sensor,
        "temperature": round(value if value is not None else random.uniform(18.0, 26.0), 1),
        "unit": "C",
        "ts": round(time.time(), 3),
    }


def encode_json(data) -> bytes:
    """JSON으로 적는다. HTTP, WebSocket, CoAP가 쓴다."""
    return json.dumps(data, separators=(",", ":")).encode()


def encode_compact(data) -> bytes:
    """가장 짧게 적는다. 값만 적고 나머지는 약속으로 두는 방식이다.

    MQTT나 CoAP처럼 좁은 망에서 도는 프로토콜은 보통 이렇게 한다. 센서 이름은
    주제나 경로가 이미 말해 주니 본문에 또 적을 까닭이 없다.
    """
    return f"{data['temperature']}".encode()


def describe(label, wire_bytes, payload_bytes):
    """한 건이 몇 바이트였는지 같은 꼴로 찍는다. 프로토콜끼리 견줄 때 쓴다."""
    overhead = wire_bytes - payload_bytes
    ratio = (payload_bytes / wire_bytes * 100) if wire_bytes else 0
    print(f"  [{label}] 전체 {wire_bytes}바이트 = 실제 값 {payload_bytes} + 규약 {overhead}"
          f"  (값이 차지하는 비율 {ratio:.1f}%)")
