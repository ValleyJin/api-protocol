# 05. gRPC — 계약서를 파일로 적는다

## 무엇을 배우는가

앞의 네 가지와 결정적으로 다른 점은 **내가 프로토콜을 적지 않는다**는 것이다. `sensor.proto`가 계약서다.

```protobuf
service SensorService {
  rpc Get(SensorId) returns (Reading);
  rpc Set(SetRequest) returns (Reading);
  rpc Watch(SensorId) returns (stream Reading);
}
```

이 파일에서 서버 코드와 클라이언트 코드를 함께 만들어 낸다. REST는 "GET /sensors/living-room 하면 JSON이 온다"를 문서에 적어 두고 사람이 읽어 맞춘다. gRPC는 필드 이름을 틀리면 실행 전에 걸린다.

### 계층별로 무엇이 정해지는가

| | 메서드 | 상태 | 본문 모양 | 타입 |
|---|---|---|---|---|
| 소켓 API | 내가 | 내가 | 내가 | 없다 |
| REST | HTTP가 | HTTP가 | 내가 | 없다 |
| gRPC | `.proto`가 | gRPC가 | `.proto`가 | `.proto`가 |

### protobuf — 필드 이름을 싣지 않는다

```
protobuf  34바이트: b'\n\x0bliving-room\x11\x00\x00\x00\x00\x00\x005@\x1a\x01C!\xf0\xa7\x86\xe0\xf1\xae\xdaA'
JSON      70바이트: {"id":"living-room","temperature":21.0,"unit":"C","ts":1790691202.104}
```

51% 줄었다. 까닭이 둘이다. 하나는 필드 이름을 싣지 않는 것이다. `temperature`라는 글자 대신 `.proto`에 적힌 번호 `2`만 싣는다. 받는 쪽도 같은 `.proto`를 갖고 있어야 `2`가 temperature임을 안다. **그래서 사람이 읽을 수 없다.**

또 하나는 proto3가 기본값인 필드를 아예 싣지 않는 것이다. 온도가 정확히 0.0도면 `temperature` 필드가 통째로 빠져 9바이트가 더 줄고, 네 값이 모두 기본값이면 protobuf는 0바이트가 된다. `client.py set 0.0` 뒤에 `client.py size`를 돌리면 51%가 아니라 64%가 찍힌다. 긴 id를 넣으면 비율이 뚝 떨어진다. id가 41자면 36%, 100자면 23%, 5000자면 1%도 안 된다. **51%는 이 값에서 나온 숫자일 뿐이다.** id만 늘릴 때는 protobuf가 아끼는 바이트가 36 근처에 머문다. 그래서 id가 길어질수록 비율이 0%에 가까워진다. 길이 필드가 한 바이트 늘어나는 128자부터는 35, 16384자부터는 34다. `--id`로 직접 재 본다.

```
python3 client.py size --id "$(python3 -c 'print("a"*41)')"     # 36% 줄었다, 아낀 바이트 36
python3 client.py size --id "$(python3 -c 'print("a"*5000)')"   # 0.7% 줄었다, 아낀 바이트 35
```

아낀 바이트는 36에서 35로 거의 그대로인데 비율만 51%에서 0.7%로 떨어진다. 비율이 무엇에 매달린 값인지 여기서 보인다. **다만 36을 protobuf가 늘 아끼는 몫으로 읽으면 안 된다.** 아끼는 바이트에는 이름을 빼는 몫만 들어 있는 것이 아니다. JSON은 temperature와 `ts`를 글자로 적고 protobuf는 8바이트 double로 적으니 그 차이도 섞여 있다. 그래서 값이 바뀌면 36도 바뀐다. `set 0.0`을 하면 44바이트, `set -100.0`이면 38바이트로 움직인다. 한글 id를 넣으면 JSON이 `\uXXXX`로 불어 더 벌어진다. 네 값이 모두 기본값일 때 100%가 되는 것도 이 셈이 아니라 앞에 적은 기본값 생략 때문이다. **줄어드는 비율은 protobuf의 성질이 아니라 값의 성질이다.**

필드 번호는 한 번 정하면 바꾸지 않는다. 예전 클라이언트가 그 번호로 읽기 때문이다. 필드를 지울 때도 번호를 재사용하지 않고 `reserved`로 막아 둔다.

### 스트리밍이 선언 하나다

`04-application/websocket`에서는 프레임을 손으로 만들어야 했다. 여기서는 `stream` 한 단어로 선언하고 `yield` 한 줄로 구현한다.

## 준비

이 폴더만 외부 패키지가 필요하다. 대안이 없다.

```
pip install grpcio grpcio-tools
```

생성된 `sensor_pb2.py`와 `sensor_pb2_grpc.py`는 저장소에 함께 넣어 두었다. `.proto`를 고쳤을 때만 다시 만든다.

```
./generate.sh
```

### 판본이 맞아야 한다

생성 코드의 판본과 실행할 때 쓰는 라이브러리의 판본이 어긋나면 임포트부터 막힌다. 실제로 이런 오류가 뜬다.

```
gencode 7.35.1 runtime 6.33.6 — Runtime version cannot be older than the linked gencode version
The grpc package installed is at version 1.81.0, but the generated code depends on grpcio>=1.81.1
```

`grpcio-tools`의 판본을 설치된 `grpcio` 이하로 맞추면 풀린다. 이것은 이 저장소의 문제가 아니라 **코드 생성 방식이 원래 떠안는 짐**이다. REST에는 없던 일이고, 계약서를 코드로 굳혀 타입 안전을 얻는 대가다.

## 실습

```
python3 server.py                     # 창 하나
python3 client.py get                 # 다른 창
python3 client.py set 25.5
python3 client.py size                # protobuf와 JSON을 견준다
python3 client.py error               # 없는 센서를 불러 상태 코드를 본다
python3 client.py watch               # 서버가 밀어 주는 값을 받는다
```

`watch`를 띄워 놓고 다른 창에서 `set`을 돌리면, 스트림 하나로 값이 계속 들어온다. 요청은 한 번뿐이었다.

## 잃는 것

- **curl로 눌러 볼 수 없다.** 브라우저 주소창에도 못 넣는다
- **브라우저가 직접 부를 수 없다.** grpc-web과 프록시가 따로 필요하다
- **캡처를 떠도 안 읽힌다.** 바이너리에 HTTP/2 프레이밍까지 얹혀 있다
- **`.proto` 없이는 아무것도 못 한다.** 클라이언트에 그 파일을 나눠 줘야 한다

서비스끼리 부르는 내부 통신에서는 이 단점이 대개 문제가 안 된다. 바깥 개발자에게 내놓는 공개 API로는 REST가 여전히 낫다.

## 직접 확인할 것

- **필드를 하나 더해 본다.** 서버를 띄워 둔 채 `.proto`에 `double humidity = 5;`를 넣고 `./generate.sh`를 돌린다. 이미 뜬 서버는 예전 생성 코드를 들고 있으니, 새로 만든 코드로 클라이언트만 다시 돌려 본다. 필드를 더하는 것은 대개 안전하다.
- **번호를 바꿔 본다.** 서버를 띄워 둔 채 `temperature = 2`를 `= 6`으로 바꾸고 `./generate.sh`를 돌린다. 예전 번호로 보내는 서버와 새 번호로 읽는 클라이언트가 어긋나, 온도가 기본값 0.0으로 나온다. 번호를 바꾸지 말라는 말의 뜻이 여기서 드러난다.
- **캡처를 떠 본다.** `sudo tcpdump -i lo0 -A -c 20 port 9400`. REST에서는 JSON이 통째로 읽혔지만, 여기서는 `living-room` 같은 문자열 조각만 보이고 필드 이름도 숫자 값도 읽히지 않는다.
