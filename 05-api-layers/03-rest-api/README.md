# 03. REST — 자원을 URL로 드러낸다

## 무엇을 배우는가

`01-socket-api`와 견줘 보면 무엇이 달라졌는지 분명하다.

```
소켓 API   GET␊                          내가 만든 명령
REST       GET /sensors/living-room       모두가 아는 메서드 + URL
```

REST의 요점은 '명령'이 아니라 **'자원'**을 드러내는 것이다. 무엇을 할지는 HTTP 메서드가 이미 정해 두었으니, 나는 어디에 할지만 URL로 적으면 된다.

```
GET    /sensors                    목록을 읽는다
GET    /sensors/living-room        하나를 읽는다
PUT    /sensors/living-room        값을 통째로 바꾼다
DELETE /sensors/living-room        지운다 (여기서는 405로 막는다)
```

### 공짜로 얻는 것

메서드에 약속이 붙어 있다. GET은 **안전하다**(아무것도 바꾸지 않는다). PUT은 **여러 번 해도 결과가 같다**(idempotent). 이 약속이 HTTP에 이미 들어 있으니, 내 프로토콜을 몰라도 남이 만든 도구가 제 일을 한다.

- 캐시가 GET 응답을 저장해도 된다는 것을 안다
- 프록시가 실패한 PUT을 다시 보내도 된다는 것을 안다
- 로드밸런서가 실패한 GET을 다른 서버로 다시 보내도 된다는 것을 안다
- 브라우저 주소창에 URL을 넣으면 그냥 눌린다

소켓 API에서는 이 가운데 아무것도 얻지 못했다.

## 실습

```
python3 server.py                     # 창 하나
python3 client.py get                 # 다른 창
python3 client.py set 23.5
python3 client.py list
python3 client.py explore
```

`explore`가 메서드를 두루 눌러 본다.

```
GET    /sensors/living-room    → 200 됐다
PUT    /sensors/living-room    → 200 됐다
PUT    /sensors/living-room    → 400 요청이 잘못됐다      (본문에 temperature가 없다)
DELETE /sensors/living-room    → 405 그 메서드는 안 된다  (되는 것: GET, PUT)
GET    /sensors/kitchen        → 404 그런 자원이 없다
```

상태 코드만 보고도 무슨 일이 났는지 안다. 내가 정한 것이 아니라 HTTP가 정해 둔 것이라 남이 만든 도구도 그대로 알아듣는다. `405`에는 `Allow` 헤더를 반드시 함께 보내야 한다. 되는 메서드를 거기에 적으라고 HTTP 명세가 정해 두었다.

## 04-application/http와 무엇이 다른가

같은 HTTP인데 두 폴더가 있다. 보는 곳이 다르다.

- `04-application/http`는 **프로토콜**을 본다. 요청 문자열을 소켓에 직접 쓰고, `\r\n\r\n`을 손으로 찾는다
- 여기는 **API 설계**를 본다. `http.server`를 써서 HTTP 문법은 라이브러리에 맡기고, 자원을 어떻게 가르고 상태 코드를 어떻게 쓸지에 집중한다

둘을 나란히 읽으면 라이브러리가 대신 해 준 일이 정확히 무엇인지 보인다.

## 직접 확인할 것

- **브라우저로 눌러 본다.** `http://127.0.0.1:9200/sensors/living-room`을 주소창에 넣는다. 그냥 된다. 이것이 REST가 웹에서 기본이 된 까닭이다.
- **`curl -i`로 헤더를 본다.** `Cache-Control: no-cache`가 붙어 있다. 이 값을 `max-age=60`으로 바꾸면 중간 캐시가 60초 동안 서버에 묻지 않는다. 서버 코드에서 바꿔 보고 `curl -v`로 확인한다.
- **PUT을 두 번 보낸다.** 같은 값으로 두 번 보내면 결과가 같다. POST였다면 두 개가 생겼을 수도 있다. 이 차이가 idempotent라는 말의 뜻이다.
