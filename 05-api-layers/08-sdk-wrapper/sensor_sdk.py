"""SDK 계층. REST API를 감싸 '내 언어의 물건'으로 바꾼다.

가장 높은 계층이다. 쓰는 사람은 HTTP도 JSON도 보지 않는다.

    with SensorClient() as client:
        reading = client.get()
        print(reading.temperature)      # float. 파싱이 없다
        client.set(23.5)

SDK가 대신 떠안는 일이 무엇인지 아래 코드에서 그대로 드러난다.

    연결 맺고 끊기     쓰는 사람이 소켓을 열고 닫지 않는다
                       (다만 이 구현은 urllib을 써서 요청마다 새로 붙는다.
                        연결을 재사용하려면 http.client나 requests.Session을 쓴다)
    재시도와 대기      잠깐 죽은 서버를 넘긴다. 갑절씩 늘려 기다린다
    시간 제한          멈춰 있지 않게 한다
    오류 옮기기        HTTP 상태 코드를 내 언어의 예외로 바꾼다
    자료 옮기기        JSON 사전을 타입이 있는 객체로 바꾼다
    판본 표시          User-Agent에 SDK 판본을 적어 서버가 알아보게 한다

그 대신 감춰지는 것도 분명하다. 어떤 요청이 몇 번 나갔는지, 응답에 어떤
헤더가 왔는지 쓰는 사람은 모른다. 문제가 나면 SDK 안을 열어 봐야 한다.
--trace 를 켜면 그 안을 들여다볼 수 있게 해 두었다.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

VERSION = "1.0.0"
DEFAULT_BASE = "http://127.0.0.1:9200"


class SensorError(Exception):
    """이 SDK가 내는 모든 오류의 뿌리."""


class SensorNotFound(SensorError):
    """그런 센서가 없다. HTTP 404에 해당한다."""


class SensorUnavailable(SensorError):
    """서버에서 쓸 만한 답을 얻지 못했다. 닿지 못했거나 5xx가 돌아왔을 때, 재시도를 다 쓴 뒤에 난다."""


class SensorRejected(SensorError):
    """서버가 요청을 거절했다. HTTP 4xx, 그리고 다시 해도 소용없는 3xx에 해당한다."""


@dataclass(frozen=True)
class Reading:
    """센서 값 한 건. 사전이 아니라 타입이 있는 객체다."""
    sensor: str
    temperature: float
    unit: str
    ts: float

    @classmethod
    def from_json(cls, payload: dict) -> "Reading":
        return cls(sensor=payload["sensor"], temperature=float(payload["temperature"]),
                   unit=payload["unit"], ts=float(payload["ts"]))

    def __str__(self):
        return f"{self.temperature}{self.unit} ({self.sensor})"


class SensorClient:
    """센서 API를 감싼 클라이언트.

    base_url  : 서버 주소
    retries   : 몇 번까지 다시 해 볼지
    timeout   : 한 번 요청에 기다릴 초
    trace     : True면 안에서 무슨 일을 하는지 찍는다
    """

    def __init__(self, base_url=DEFAULT_BASE, retries=3, timeout=3.0, trace=False):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.timeout = timeout
        self.trace = trace
        self.request_count = 0

    def _log(self, message):
        if self.trace:
            print(f"    [SDK] {message}")

    def _request(self, method, path, payload=None):
        """재시도와 오류 옮기기를 여기서 한다. 바깥에서는 안 보인다."""
        url = self.base_url + path
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"User-Agent": f"sensor-sdk/{VERSION}", "Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"

        if not isinstance(self.retries, int) or isinstance(self.retries, bool) \
                or self.retries < 1:
            # 0을 넣으면 루프가 한 번도 안 돌아 요청 없이 예외가 난다.
            # README가 재시도 횟수를 바꿔 보라고 하니 0을 넣는 사람이 나온다.
            # 1.5나 "3" 처럼 1 이상이어도 range() 에서 터지는 값이 있어 함께 막는다.
            raise ValueError(
                f"retries 는 1 이상인 정수여야 한다 (받은 값: {self.retries!r})")

        wait = 0.2
        last_error = None
        for attempt in range(1, self.retries + 1):
            self.request_count += 1
            self._log(f"{method} {url} ({attempt}/{self.retries}번째)")
            request = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    raw = resp.read()
                    self._log(f"{resp.status} 응답 {len(raw)}바이트")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as exc:
                        # 2xx인데 JSON이 아닐 수 있다. 204처럼 본문이 비었거나
                        # 앞단이 HTML 오류 쪽을 끼워 넣었을 때다. 이것을 그냥
                        # 올려 보내면 SensorError 로 감싼 쪽 코드가 터진다.
                        raise SensorRejected(
                            f"{resp.status} 응답이 JSON이 아니다 "
                            f"({len(raw)}바이트)") from exc
            except urllib.error.HTTPError as exc:
                # 4xx는 다시 해 봐야 소용없다. 바로 예외로 바꾼다.
                detail = exc.read().decode(errors="replace")
                if 400 <= exc.code < 500:
                    self._log(f"HTTP {exc.code} — 요청 쪽 문제다. 다시 하지 않는다")
                elif exc.code >= 500:
                    # 마지막 시도에서는 다시 하지 않는다. 로그가 앞질러 말하면
                    # 화면과 실제 행동이 어긋난다.
                    tail = "다시 해 본다" if attempt < self.retries else "다시 할 횟수를 다 썼다"
                    self._log(f"HTTP {exc.code} — 서버 쪽 오류다. {tail}")
                else:
                    # 3xx도 HTTPError로 올라온다. urllib이 따라가지 못한 리다이렉트나
                    # 304처럼 본문이 없는 응답이다. 다시 해도 같은 답이 온다.
                    self._log(f"HTTP {exc.code} — 재시도로 풀릴 응답이 아니다")
                    raise SensorRejected(
                        f"서버가 뜻밖의 응답을 보냈다 ({exc.code}): {detail}") from exc
                if exc.code == 404:
                    raise SensorNotFound(f"그런 센서가 없다: {path}") from exc
                if 400 <= exc.code < 500:
                    raise SensorRejected(f"서버가 거절했다 ({exc.code}): {detail}") from exc
                last_error = exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                # 닿지 못한 것은 다시 해 볼 만하다.
                last_error = exc
                self._log(f"닿지 못했다: {exc}")

            if attempt < self.retries:
                self._log(f"{wait:.1f}초 기다렸다 다시 한다")
                time.sleep(wait)
                wait *= 2      # 갑절씩 늘린다

        raise SensorUnavailable(
            f"{self.retries}번 해 봤지만 {url} 에서 쓸 만한 답을 얻지 못했다: {last_error}") from last_error

    # ── 바깥에 내놓는 것은 이 셋뿐이다 ────────────────────────────────
    def get(self, sensor_id="living-room") -> Reading:
        """최근 값을 읽는다."""
        return Reading.from_json(self._request("GET", f"/sensors/{sensor_id}"))

    def set(self, temperature: float, sensor_id="living-room") -> Reading:
        """값을 올린다."""
        return Reading.from_json(
            self._request("PUT", f"/sensors/{sensor_id}", {"temperature": temperature}))

    def list(self):
        """센서 목록을 읽는다."""
        return self._request("GET", "/sensors")["sensors"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
