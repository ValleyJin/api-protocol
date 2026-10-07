"""여덟 가지 API가 함께 쓰는 센서 저장소.

API 방식만 다르고 아래에 놓인 자료는 같아야 견주는 뜻이 있다. 그래서 값을
들고 있는 부분을 여기 한 번만 적는다.

각 폴더는 이 저장소에 두 가지 일만 시킨다.

    get()          최근 값을 읽는다
    set(value)     값을 올린다

이 두 가지를 여덟 가지 방식으로 바깥에 내놓는 것이 05 폴더의 실습이다.
"""

import math
import threading
import time

_LOCK = threading.Lock()
_STATE = {"sensor": "living-room", "temperature": 21.0, "unit": "C", "ts": round(time.time(), 3)}


def get():
    with _LOCK:
        return dict(_STATE)


def set_value(value: float):
    value = float(value)
    # inf 와 nan 을 막는다. 파이썬 json 은 이것을 Infinity, NaN 으로 적어 주지만
    # JSON 명세에는 없는 값이라 다른 언어 클라이언트에서 깨진다. 한 번 들어오면
    # 그 뒤의 모든 응답이 JSON이 아니게 되니 들어오는 자리에서 막는다.
    if not math.isfinite(value):
        raise ValueError(f"temperature 는 유한한 수여야 한다 (받은 값: {value})")
    with _LOCK:
        _STATE["temperature"] = round(value, 1)
        _STATE["ts"] = round(time.time(), 3)   # 자릿수를 줄여 흔들림을 한두 바이트로 묶어 둔다
        return dict(_STATE)


def line_count(path):
    """파일의 줄 수를 센다. 계층별로 코드가 얼마나 줄어드는지 볼 때 쓴다."""
    try:
        with open(path, encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip() and not line.strip().startswith("#"))
    except OSError:
        return 0
