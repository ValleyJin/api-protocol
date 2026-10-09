#!/usr/bin/env python3
"""이 기기의 네트워크 인터페이스와 MAC 주소를 뽑는다.

1층은 "이 기기가 선에 닿는 지점"이다. 그 지점마다 이름과 MAC 주소가 있다.
뒤의 실습에서 어느 인터페이스를 캡처할지 고를 때 여기서 나온 이름을 쓴다.

MAC 주소를 표준 라이브러리만으로 뽑는 방법은 운영체제마다 다르다. 리눅스는
/sys/class/net/<이름>/address 파일을 읽으면 되고, macOS는 그런 파일이 없어
ifconfig 출력을 읽는다. 두 방법을 다 적어 두었다.

    python3 list_interfaces.py
"""

import pathlib
import re
import socket
import subprocess
import sys


def macs_from_sysfs():
    """리눅스: /sys/class/net 에서 읽는다. 커널이 그대로 내주는 값이다."""
    result = {}
    base = pathlib.Path("/sys/class/net")
    if not base.is_dir():
        return result
    for entry in base.iterdir():
        addr = entry / "address"
        if addr.is_file():
            result[entry.name] = addr.read_text().strip()
    return result


def macs_from_ifconfig():
    """macOS와 BSD: ifconfig 출력에서 ether 줄을 찾는다."""
    result = {}
    try:
        out = subprocess.run(["ifconfig", "-a"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return result
    name = None
    for line in out.splitlines():
        if line and not line[0].isspace():
            name = line.split(":")[0]
        elif name:
            m = re.search(r"\bether\s+([0-9a-f:]{17})", line)
            if m:
                result[name] = m.group(1)
    return result


def addresses(name):
    """인터페이스에 붙은 IPv4 주소를 찾는다. 없으면 빈 목록이다."""
    found = []
    try:
        out = subprocess.run(["ifconfig", name], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        try:
            out = subprocess.run(["ip", "-o", "addr", "show", name],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return found
    for m in re.finditer(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out):
        found.append(m.group(1))
    return found


def main():
    macs = macs_from_sysfs() or macs_from_ifconfig()

    # socket.if_nameindex()는 커널이 붙인 인터페이스 번호와 이름을 그대로 준다.
    # 표준 라이브러리만으로 목록을 얻는 가장 곧은 길이다.
    try:
        interfaces = socket.if_nameindex()
    except (AttributeError, OSError) as exc:
        print(f"인터페이스 목록을 얻지 못했다: {exc}", file=sys.stderr)
        return 1

    print(f"{'번호':<5} {'이름':<14} {'MAC 주소':<19} IPv4")
    print("-" * 64)
    for index, name in interfaces:
        mac = macs.get(name, "-")
        ips = ", ".join(addresses(name)) or "-"
        print(f"{index:<5} {name:<14} {mac:<19} {ips}")

    print()
    print("읽는 법")
    print("  MAC 주소가 '-'인 인터페이스는 이더넷 헤더를 쓰지 않는다.")
    print("  루프백(lo0, lo)이 그렇다. 06 폴더에서 이 차이가 오버헤드 계산을 바꾼다.")
    print("  MAC 주소 앞 3바이트는 OUI라 부르고 랜카드를 만든 회사를 가리킨다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
