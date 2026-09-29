# MQTT — 발행-구독 메시징

## 무엇을 배우는가

지금까지 넷은 모두 요청-응답이거나 양방향 연결이었다. 어느 쪽이든 **보내는 쪽과 받는 쪽이 서로를 알고** 있었다. MQTT는 그 고리를 끊는다.

```
발행자 ──PUBLISH──▶ 브로커 ──PUBLISH──▶ 구독자
                      ▲
              구독자가 미리 SUBSCRIBE 해 둔 주제로만 간다
```

발행자는 구독자가 몇 명인지, 누구인지, 지금 붙어 있는지 모른다. 주제(topic) 이름만 안다. 구독자도 발행자를 모른다. 가운데 브로커가 주제별로 나눠 준다.

이 구조가 무엇을 가능하게 하는지가 요점이다. 센서 천 개와 대시보드 세 개를 잇는데 각자가 상대를 알 필요가 없다. 센서를 하나 더 붙여도 대시보드 코드를 안 고친다.

### 패킷

모두 같은 꼴로 시작한다.

```
┌───────────────────┬─────────────────┐
│ 종류(4) 플래그(4) │  남은 길이(1~4) │  + 가변 헤더 + 본문
└───────────────────┴─────────────────┘
```

'남은 길이'는 한 바이트에 7비트씩 담고 맨 앞 비트로 "아직 더 있다"를 표시한다. 그래서 127바이트 이하 메시지는 길이 필드가 **1바이트**로 끝난다. HTTP의 `Content-Length: 74`가 글자 열아홉 개를 쓰는 것과 견줘 보면 설계 방향이 그대로 드러난다.

### QoS — 어디까지 보장할지 고른다

| QoS | 뜻 | 오가는 패킷 |
|---|---|---|
| 0 | 한 번 보내고 만다 | PUBLISH |
| 1 | 적어도 한 번 닿는다 (겹칠 수 있다) | PUBLISH → PUBACK |
| 2 | 딱 한 번 닿는다 | PUBLISH → PUBREC → PUBREL → PUBCOMP |

TCP가 이미 도착을 보장하는데 왜 또 필요한가. TCP는 **연결이 살아 있는 동안**만 보장한다. 연결이 끊기면 그 순간 날아가던 메시지는 사라진다. QoS는 연결을 넘어선 보장이다.

### retain과 clean session

둘 다 "지금 없는 사람에게 어떻게 전할까"를 다루지만 방식이 다르다.

**retain**은 주제마다 마지막 한 건을 브로커가 들고 있다가, 새로 구독한 사람에게 곧바로 한 번 보내 준다. 없으면 새 구독자는 다음 값이 올 때까지 아무것도 모른다. 온도처럼 "현재 상태"가 있는 값에 쓴다.

**clean session**을 끄면 브로커가 그 client id의 세션을 기억한다. 구독자가 끊겨 있는 동안 온 QoS 1 이상 메시지를 쌓아 두었다가 다시 붙으면 몰아 준다. QoS 0은 쌓지 않는다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `mqtt.py` | MQTT 3.1.1 패킷을 만들고 읽는 최소 구현 |
| `broker.py` | 브로커. 구독 관리, retain, 세션 유지까지 한다 |
| `publisher.py` | 발행자 |
| `subscriber.py` | 구독자 |
| `parse_mqtt.py` | 캡처에서 MQTT 패킷을 뽑아 읽는다 |

Mosquitto를 깔지 않아도 된다. 브로커를 직접 만들어 넣었다.

## 만들 것

- 브로커를 띄우고 발행자와 구독자를 각각 구현
- CONNECT, PUBLISH, SUBSCRIBE 패킷을 바이트로 뜯어 보는 파서
- QoS 0, 1, 2에서 오가는 패킷 수를 각각 세어 견주기

## 확인하는 법

### 1. 기본 흐름

```
python3 broker.py                     # 창 하나
python3 subscriber.py                 # 창 둘
python3 publisher.py 23.5             # 창 셋
```

### 2. retain 실습

```
python3 broker.py                     # 창 하나
python3 publisher.py 23.5 --retain    # 구독자가 없는 채로 올린다
python3 subscriber.py                 # 붙자마자 23.5가 온다
```

`--retain` 없이 하면 구독자가 아무것도 못 받는다. 그 차이가 retain이다. 구독자 출력에 `[retain된 값]` 표시가 붙는다.

### 3. clean session 실습

조건이 **네 개** 모두 맞아야 한다. 하나라도 빠지면 아무것도 안 온다.

```
python3 broker.py                                  # 창 하나

python3 subscriber.py --persist --qos 1            # 창 둘
# Ctrl+C로 끈다

python3 publisher.py 24.0 --qos 1                  # 끊겨 있는 동안 올린다

python3 subscriber.py --persist --qos 1            # 다시 붙으면 24.0이 몰려 온다
```

| 조건 | 빠지면 |
|---|---|
| 구독자 `--persist` (clean_session=False) | 세션이 안 남아 구독부터 사라진다 |
| 구독자 고정 client id | 브로커가 같은 세션으로 알아보지 못한다 |
| 구독 QoS 1 이상 | 전달 QoS가 0이 되어 쌓이지 않는다 |
| **발행 QoS 1 이상** | QoS 0 메시지는 브로커가 쌓지 않는다 |

실제 전달 QoS는 **발행 QoS와 구독 QoS 가운데 작은 쪽**이다. 구독만 QoS 1로 걸어도 발행이 0이면 0으로 떨어진다. `paho-mqtt`의 `publish()` 기본값이 QoS 0이라 여기서 많이 막힌다.

### 4. 순서가 뒤바뀌는 것을 본다

3번을 돌리면 구독자 출력에 `SUBACK보다 먼저 왔다`가 뜬다. 세션을 되살리면 브로커가 CONNACK 바로 뒤에 쌓아 둔 PUBLISH를 몰아 보내기 때문이다.

"보낸 순서대로 답이 온다"고 여기고 짜면 여기서 깨진다. `subscriber.py`의 `Connection.next_packet()`처럼 종류를 보고 갈라 처리해야 한다.

### 5. 캡처를 떠서 바이트를 센다

```
mkdir -p samples
sudo tcpdump -i lo0 -w samples/mqtt.pcap port 1883 &
python3 broker.py &
python3 publisher.py 23.5 --retain --qos 1
sleep 1 && sudo pkill tcpdump
python3 parse_mqtt.py samples/mqtt.pcap
```

`parse_mqtt.py`가 TCP 스트림을 다시 이어 붙인다. MQTT 패킷 하나가 TCP 세그먼트 둘에 걸쳐 오기도 하고, 세그먼트 하나에 패킷 셋이 담겨 오기도 하기 때문이다. 실제 프로토콜 분석기가 하는 일이 이것이다.

### 6. `paho-mqtt`와 견준다

```
pip install paho-mqtt
```

직접 만든 구현과 같은 브로커에 붙는다. 코드가 얼마나 줄고, 실제로 오가는 바이트는 같은지 캡처로 확인한다.

## 실제로 재어 본 값

```
CONNECT      25바이트
PUBLISH      36바이트 (주제 28 + 값 4 + 헤더 4)  QoS 0
PUBLISH      38바이트  QoS 1 (packet id 2바이트가 더 붙는다)
PUBACK        4바이트
```

주제 이름을 매번 실어 보낸다. 주제가 길면 그만큼 불어난다. `home/living-room/temperature`가 28바이트고 값은 4바이트다. 주제 설계가 대역폭에 그대로 영향을 준다.

대신 한 번 붙어 두면 여러 건을 그 연결로 계속 보낸다. HTTP는 매번 새로 붙는다.

## 자주 막히는 곳

| 증상 | 까닭 |
|---|---|
| retain 값이 안 온다 | 발행할 때 `--retain`을 안 켰다 |
| 쌓아 둔 값이 안 온다 | 위 3번 표의 네 조건 가운데 하나가 빠졌다 |
| 구독자가 SUBACK에서 깨진다 | PUBLISH가 먼저 왔다. 패킷 종류로 갈라야 한다 |
| 브로커가 연결을 바로 끊는다 | CONNECT 없이 다른 패킷을 먼저 보냈다 |
