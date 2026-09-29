# HTTP — 요청-응답

## 무엇을 배우는가

HTTP/1.1은 TCP 위에 얹힌 **텍스트 프로토콜**이다. 이 말이 과장이 아니라는 것을 소켓으로 직접 확인한다. 보내는 것은 그저 아래 글자다.

```
GET /path HTTP/1.1␍␊
Host: example.com␍␊
Connection: close␍␊
␍␊
```

줄 끝은 `\r\n`이고, **빈 줄 하나가 헤더의 끝**을 알린다. 03 폴더에서 본 대로 TCP는 메시지 경계를 지켜 주지 않으니, HTTP가 빈 줄로 경계를 스스로 정한 것이다. 본문 길이는 `Content-Length` 헤더가 알려 준다.

HTTP/2는 이 텍스트를 바이너리 프레임으로 바꿨고, HTTP/3은 TCP 대신 UDP 위 QUIC에서 돈다. 여기서는 HTTP/1.1을 확인한다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `raw_client.py` | 소켓에 요청 문자열을 직접 써서 보낸다 |
| `minimal_server.py` | 요청 줄과 헤더를 직접 파싱하는 서버 |
| `lib_client.py` | 같은 요청을 `http.client`와 `requests`로 보내 견준다 |

## 만들 것

- 라이브러리를 전혀 쓰지 않고 요청 줄과 헤더만 조립해 응답을 받아 내는 최소 클라이언트
- 요청 줄과 헤더를 파싱해 응답하는 최소 서버
- 같은 일을 `http.client`(표준 라이브러리)나 `requests`(외부 패키지)로 다시 구현

## 확인하는 법

### 1. 바깥 서버에 직접 말을 건다

```
python3 raw_client.py example.com /
```

보낸 글자와 받은 글자를 그대로 찍는다. 응답 헤더가 본문보다 클 때가 많다는 것을 확인한다.

### 2. 서버까지 직접 만든다

```
python3 minimal_server.py                                    # 창 하나
python3 raw_client.py --port 8080 127.0.0.1 /sensors/living-room/temperature
curl -X PUT -d '{"temperature":22.5}' localhost:8080/sensors/living-room/temperature
```

서버 코드에서 눈여겨볼 곳은 `\r\n\r\n`을 찾을 때까지 읽는 부분과 `Content-Length`만큼 본문이 다 왔는지 확인하는 부분이다. 프레임워크를 쓰면 안 보이는 일이다.

### 3. 라이브러리와 견준다

```
python3 lib_client.py --port 8080 127.0.0.1 /sensors/living-room/temperature
```

코드 줄 수는 줄고 실제로 오가는 바이트는 늘어난다. `requests`가 `User-Agent`, `Accept-Encoding`을 알아서 붙이기 때문이다. 내가 적지 않은 바이트가 흐른다.

### 4. Keep-Alive를 켜고 끈다

`raw_client.py`는 `Connection: close`를 늘 붙이고 `minimal_server.py`도 응답마다 연결을 닫는다. 두 파일에서 그 헤더를 빼고 같은 연결로 두 번 요청하도록 고쳐 보면, 캡처에서 핸드셰이크가 한 번만 일어나는 것이 보인다.

```
sudo tcpdump -i lo0 -A -c 20 port 8080
```

## 견줄 것

같은 값 하나를 받는 데 HTTP는 요청 120 + 응답 199바이트를 썼다. 본문은 74바이트다. 나머지 245바이트는 규약이 쓴 것이다. `../coap/`에서 같은 일을 38 + 83바이트로 하는 것을 보고 왜 그런 차이가 나는지 생각해 본다.

## 자주 막히는 곳

| 증상 | 까닭 |
|---|---|
| 응답이 안 끝나고 멈춰 있다 | `Connection: close`를 안 보냈다. 서버가 더 올 줄 알고 기다린다 |
| 한글이 깨져 보인다 | `Content-Type`에 `charset=utf-8`이 없거나 터미널 인코딩 문제다 |
| 서버가 400을 돌려준다 | 첫 줄이 `GET /경로 HTTP/1.1` 세 토막이 아니다. 빈 줄을 안 보냈을 때는 400 대신 답이 아예 안 온다 |
