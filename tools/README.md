# tools — 여러 폴더가 함께 쓰는 도구

01, 02, 03, 04, 06 폴더가 이 패키지를 임포트한다. 캡처 파일을 읽고 바이트를 사람이 볼 수 있게 찍는 일을 여기에 한 번만 적어 두었다.

| 파일 | 하는 일 |
|---|---|
| `pcap.py` | pcap 파일을 읽어 패킷을 하나씩 돌려준다 |
| `hexdump.py` | 바이트를 16진수로 찍고 필드 경계를 표시한다 |
| `make_sample_pcap.py` | 실습용 표본 pcap을 지어낸다 |
| `paths.py` | 하위 폴더 스크립트가 이 패키지를 찾는 방법을 적어 둔 메모 |

## 임포트하는 방법

하위 폴더의 스크립트는 맨 위에 이렇게 적는다.

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.pcap import PcapFile
```

폴더가 두 겹 아래(`04-application/mqtt` 등)면 `parents[2]`로 적는다.

## pcap 파일 구조

`pcap.py`를 읽기 전에 알아 두면 좋다. 24바이트 전역 헤더가 한 번 나오고, 그 뒤에 [16바이트 패킷 헤더 + 데이터]가 끝까지 되풀이된다.

```
전역 헤더 (24바이트)
┌────────┬─────┬─────┬────────┬────────┬────────┬─────────┐
│ magic  │major│minor│thiszone│ sigfigs│ snaplen│ network │
│  4     │  2  │  2  │   4    │    4   │    4   │    4    │
└────────┴─────┴─────┴────────┴────────┴────────┴─────────┘

패킷 헤더 (16바이트)
┌────────┬─────────┬──────────┬──────────┐
│ ts_sec │ ts_usec │ incl_len │ orig_len │
└────────┴─────────┴──────────┴──────────┘
```

`magic` 값이 바이트 순서를 알려 준다. `network` 필드는 링크 계층 종류(linktype)를 나타낸다. 이 값에 따라 패킷 데이터가 무엇으로 시작하는지 달라진다. 이더넷 헤더일 수도 있고, BSD 루프백의 4바이트 AF 값일 수도 있고, 곧바로 IP 헤더일 수도 있다. 06 폴더에서 오버헤드를 셀 때 이 값이 중요하다.

`incl_len`은 파일에 담긴 길이이고 `orig_len`은 네트워크에 실제로 흐른 원래 길이다. `snaplen`을 짧게 걸고 잡으면 둘이 달라진다.

## pcapng는 못 읽는다

이 리더는 예전 pcap만 읽는다. Wireshark의 기본 저장 형식은 pcapng다.

```
tcpdump -w out.pcap                      # 이렇게 뜨면 pcap이다
editcap -F pcap in.pcapng out.pcap       # 이미 pcapng라면 바꾼다
```

pcapng는 블록 구조라 훨씬 복잡하다. 이 저장소의 목적(헤더를 손으로 뜯어보기)에는 단순한 pcap이 알맞다.
