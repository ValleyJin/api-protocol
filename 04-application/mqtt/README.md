# MQTT — 발행-구독 메시징

## 목표
보내는 쪽과 받는 쪽이 서로를 모른 채 주제(topic)로만 이어지는 구조를 확인한다.

## 만들 것
- 브로커를 띄우고 발행자와 구독자를 각각 구현 (`paho-mqtt` 등)
- CONNECT, PUBLISH, SUBSCRIBE 패킷을 바이트로 뜯어 보는 파서
- QoS 0, 1, 2에서 오가는 패킷 수를 각각 세어 견주기

## 확인하는 법
1. 브로커(Mosquitto 등)를 띄우고 구독자를 먼저 연결한다.
2. 발행자가 값을 올리면 구독자가 받는지 확인한다.
3. 구독자를 껐다가 값을 올린 뒤 다시 켠다. retain과 clean session이 어떻게 달라지는지 본다. retain은 발행할 때 retain 플래그를 켜야 남는다. clean session을 견주려면 구독자가 고정 client id로 `clean_session=False`를 걸고 QoS 1 이상으로 구독해야 한다. `paho-mqtt` 기본값(QoS 0, clean session 켬)으로는 둘 다 빈손으로 나온다.
4. 캡처로 PUBLISH 패킷 한 건의 실제 바이트 수를 잰다.
