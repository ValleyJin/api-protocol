#!/usr/bin/env bash
# 실습용 캡처를 뜬다. tcpdump를 감싸 두어 옵션을 외우지 않아도 되게 했다.
#
#   ./capture.sh en0 arp 20        # en0에서 ARP 프레임 20개
#   ./capture.sh lo0 tcp 40        # lo0에서 TCP 40개 (이더넷 헤더는 없다)
#
# 저장 형식은 pcap이다. tools/pcap.py가 읽는 형식이 이것이다.
set -euo pipefail

iface="${1:?사용법: ./capture.sh <인터페이스> [필터] [개수]}"
filter="${2:-}"
count="${3:-20}"
out="samples/${iface}-${filter:-all}.pcap"

mkdir -p samples
echo "인터페이스 ${iface} 에서 ${count}개를 잡아 ${out} 에 저장한다."
echo "관리자 권한이 필요하다."
sudo tcpdump -i "$iface" -c "$count" -w "$out" ${filter:+$filter}
echo "저장했다: ${out}"
echo "다음: python3 parse_ethernet.py ${out}"
