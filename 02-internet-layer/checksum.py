#!/usr/bin/env python3
"""인터넷 체크섬을 구한다. IP 헤더와 ICMP가 같은 방식을 쓴다.

셈법은 간단하다. 데이터를 2바이트씩 잘라 모두 더하고, 넘친 자리(캐리)를
아래로 돌려 더한 뒤, 마지막에 비트를 뒤집는다. 이것을 1의 보수 합이라고 한다.

받는 쪽은 체크섬 자리까지 포함해 같은 셈을 한다. 결과가 0이면 헤더가 온전하다.
값을 새로 구하는 것이 아니라 0인지만 보면 되니 라우터가 빠르게 확인한다.

    python3 checksum.py          # 자체 검사를 돌린다
"""

import struct


def internet_checksum(data: bytes) -> int:
    """1의 보수 합을 구해 16비트 체크섬을 돌려준다."""
    if len(data) % 2:
        data += b"\x00"  # 홀수 길이면 0을 하나 붙여 2바이트씩 맞춘다
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:                      # 16비트를 넘친 자리를
        total = (total & 0xFFFF) + (total >> 16)   # 아래로 돌려 더한다
    return ~total & 0xFFFF                  # 마지막에 뒤집는다


def verify(data: bytes) -> bool:
    """체크섬 자리를 포함한 데이터를 넣으면 온전한지 알려 준다."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total == 0xFFFF


def _self_test():
    # RFC 1071이 예로 드는 바이트열
    sample = bytes([0x00, 0x01, 0xf2, 0x03, 0xf4, 0xf5, 0xf6, 0xf7])
    got = internet_checksum(sample)
    print(f"RFC 1071 예제       : 0x{got:04x} (기대값 0x220d)")
    assert got == 0x220D, got

    # 진짜 IP 헤더로 확인한다. 체크섬 자리를 0으로 두고 구하면 원래 값이 나온다.
    header = bytes.fromhex("4500003c1c4640004006" + "0000" + "ac100a63ac100a0c")
    original = 0xB1E6
    got = internet_checksum(header)
    print(f"IP 헤더에서 다시 구함: 0x{got:04x} (원래 값 0x{original:04x})")
    assert got == original, hex(got)

    # 체크섬을 끼워 넣은 헤더는 검사를 통과해야 한다.
    filled = header[:10] + struct.pack("!H", got) + header[12:]
    print(f"검사 통과 여부       : {verify(filled)}")
    assert verify(filled)

    # 한 바이트만 망가뜨리면 검사가 걸러야 한다.
    broken = bytearray(filled)
    broken[16] ^= 0x01
    print(f"1바이트 망가뜨린 뒤  : {verify(bytes(broken))} (False여야 맞다)")
    assert not verify(bytes(broken))
    print("\n자체 검사를 모두 통과했다.")


if __name__ == "__main__":
    _self_test()
