# 08. SDK — API를 내 언어의 물건으로 바꾼다

## 무엇을 배우는가

`03-rest-api`와 `05-grpc-api` 위에 얹히는 가장 높은 계층이다. 쓰는 사람은 HTTP도 JSON도 보지 않는다.

```python
with SensorClient() as client:
    reading = client.get()
    print(reading.temperature)      # float. 파싱이 없다
    client.set(23.5)
```

SDK는 새 프로토콜이 아니다. `03-rest-api`를 그대로 부른다. 그 위에 한 겹을 얹은 것뿐이다. 하지만 그 한 겹이 하는 일이 적지 않다.

| SDK가 하는 일 | 없으면 누가 하는가 |
|---|---|
| 연결 맺고 끊기 | 쓰는 사람 |
| 재시도와 갑절씩 늘려 기다리기 | 쓰는 사람 |
| 시간 제한 | 쓰는 사람 |
| HTTP 상태 코드를 예외로 옮기기 | 쓰는 사람 |
| JSON 사전을 타입 있는 객체로 옮기기 | 쓰는 사람 |
| 판본을 `User-Agent`에 적기 | 아무도 안 한다 |

이 여섯 가지를 앱마다 되풀이해 적는 대신 한 번 적어 나눠 주는 것이 SDK다.

## 실습

```
python3 ../03-rest-api/server.py &
python3 demo.py
python3 demo.py --trace
python3 demo.py --fail
```

## 오류를 내 언어로 옮긴다

```
client.get('kitchen')  →  SensorNotFound: 그런 센서가 없다
client.set('스물넷')   →  SensorRejected: 서버가 거절했다 (400)
서버가 없을 때         →  SensorUnavailable: 3번 해 봤지만 닿지 못했다
```

쓰는 사람이 `404`라는 숫자를 알 필요가 없다. `except SensorNotFound:`로 잡는다. 서버가 상태 코드 체계를 바꿔도 SDK만 고치면 된다.

**4xx는 다시 하지 않고 곧바로 예외로 바꾼다.** 요청 자체가 잘못됐으니 백 번을 해도 마찬가지다. 닿지 못한 것(연결 거절, 시간 초과)과 서버 쪽 오류(5xx)는 다시 해 본다. 이 구분을 안 하면 잘못된 요청을 세 번씩 보내며 서버를 괴롭힌다.

## 감춰지는 것

```
python3 demo.py
→ HTTP 요청 4번
```

쓰는 쪽 코드에는 '요청'이라는 말이 한 번도 안 나왔다. 그런데 네 번 나갔다. 이것이 SDK가 주는 편함이자 그 편함의 대가다.

그래서 느려져도 쓰는 사람은 까닭을 알 수 없다. SDK 안을 열지 않고는 재시도가 몇 번 돌았는지, 얼마나 기다렸는지 모른다. 그래서 `--trace`를 만들어 두었다.

```
python3 demo.py --fail --trace

    [SDK] GET http://127.0.0.1:9999/sensors/living-room (1/3번째)
    [SDK] 닿지 못했다: Connection refused
    [SDK] 0.2초 기다렸다 다시 한다
    [SDK] GET ... (2/3번째)
    [SDK] 0.4초 기다렸다 다시 한다
    [SDK] GET ... (3/3번째)
  0.6초 동안 3번 해 보고 포기했다
```

**좋은 SDK는 자기 안을 들여다볼 창을 함께 준다.** 로그 훅, 요청 추적, 재시도 통계 같은 것이다. 없으면 쓰는 사람이 패킷을 캡처해야 한다.

## 타입이 있으면 달라지는 것

`Reading`은 얼려 둔 데이터클래스다.

```
reading.temperature = 0   →  FrozenInstanceError
```

사전이었다면 그냥 바뀐다. 얼려 두면 서버에서 받은 값을 실수로 고쳐 쓰고 그것이 옳은 값이라고 믿는 사고를 막는다. 필드 이름을 틀리면 `AttributeError`가 바로 난다. 사전이었다면 `KeyError`가 한참 뒤에 엉뚱한 곳에서 난다.

`05-grpc-api`는 이 타입을 `.proto`에서 자동으로 만들어 낸다. SDK를 손으로 짜는 대신 계약서에서 뽑아내는 셈이다.

## 직접 확인할 것

- **재시도 횟수를 바꿔 본다.** `SensorClient(retries=6)`으로 `--fail`을 돌린다. 0.2초에서 갑절씩 늘어나 6번이면 얼마나 기다리는지 계산해 본다. 이 값이 클수록 쓰는 사람은 더 오래 기다린다.
- **4xx에 재시도를 걸어 본다.** `_request()`에서 4xx도 다시 하게 고치고 `client.set('스물넷')`을 부른다. 잘못된 요청을 세 번 보내는 것을 확인한다.
- **`Reading`에 필드를 더한다.** 서버가 `humidity`를 보내기 시작했다고 하자. `from_json()`을 안 고치면 어떻게 되는지 본다. 모르는 필드를 무시할지 오류를 낼지는 설계 선택이다.
