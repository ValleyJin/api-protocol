# CoAP — 초경량 IoT

## 목표
저사양 기기를 위해 UDP 위에서 도는 요청-응답 프로토콜을 확인한다.

## 만들 것
- CoAP 서버와 클라이언트 (`aiocoap` 등)
- 같은 리소스를 HTTP로도 열어 두고 메시지 크기를 견주는 스크립트
- Observe 옵션으로 값이 바뀔 때 알림을 받는 구현

## 확인하는 법
1. GET 한 번에 오가는 바이트 수를 HTTP 버전과 견준다.
2. 서버를 내리거나 ACK를 막아 둔 채, Confirmable은 재전송하고 Non-confirmable은 재전송하지 않는 것을 확인한다.
3. 순서가 뒤바뀌거나 유실되는 상황을 일부러 만든다. 리눅스는 `tc qdisc add dev lo root netem loss 30% delay 50ms reorder 25%`를 걸고, macOS는 `dnctl`과 `pfctl`로 파이프를 건다. 도구가 없으면 클라이언트 코드에서 보내는 패킷을 확률로 버린다.
