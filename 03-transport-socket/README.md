# 03. 전송 계층과 소켓 API (3층)

## 목표
소켓 API만으로 서버와 클라이언트를 직접 짠다. 라이브러리 없이 스택을 손으로 만지는 단계다.

## 다루는 것
TCP, UDP, 포트, 3-way handshake, 소켓 API

## 만들 것
- TCP 에코 서버 (`socket` → `bind` → `listen` → `accept` → `recv`/`send` → `close`)
- TCP 클라이언트 (`socket` → `connect` → `send`/`recv` → `close`)
- UDP 송신기 (`socket` → `sendto`)와 수신기 (`socket` → `bind` → `recvfrom`)
- 같은 서버를 블로킹 방식과 `select` 방식으로 각각 구현해 견주기

## 확인하는 법
1. 서버를 띄운 뒤 `sudo tcpdump`로 3-way handshake(SYN, SYN-ACK, ACK)를 잡는다. 서버와 클라이언트를 한 기기에서 돌리면 트래픽이 루프백으로만 흐르니 macOS는 `-i lo0`, 리눅스는 `-i lo`를 붙인다.
2. 연결을 끊고 4-way close(FIN, ACK, FIN, ACK)까지 잡는다. 받는 쪽이 FIN과 ACK를 한 세그먼트로 묶으면 3개만 잡히기도 한다.
3. UDP로 같은 데이터를 보내고 핸드셰이크가 없다는 것을 캡처로 확인한다.
4. `netstat -an` 또는 `ss -tan`으로 소켓 상태(LISTEN, ESTABLISHED, TIME_WAIT)를 본다.

## 메모
UDP 송신기에는 `bind`가 필요 없다. `sendto`를 부르면 커널이 임시 포트를 알아서 붙인다.

여기서 만든 코드가 `05-api-layers`의 출발점이 된다. 같은 기능을 더 높은 계층의 API로 다시 짜서 견줄 것이므로 지우지 않는다.
