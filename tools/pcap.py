"""pcap 파일을 읽어 패킷을 하나씩 돌려주는 최소 리더.

표준 라이브러리만 쓴다. 01, 02, 06 폴더가 함께 쓴다.

pcap 파일 구조는 단순하다. 24바이트 전역 헤더가 한 번 나오고, 그 뒤에
[16바이트 패킷 헤더 + 패킷 데이터]가 끝까지 되풀이된다.

    전역 헤더 (24바이트)
    ┌────────┬─────┬─────┬────────┬────────┬────────┬─────────┐
    │ magic  │major│minor│thiszone│ sigfigs│ snaplen│ network │
    │  4     │  2  │  2  │   4    │    4   │    4   │    4    │
    └────────┴─────┴─────┴────────┴────────┴────────┴─────────┘

    패킷 헤더 (16바이트)
    ┌────────┬─────────┬──────────┬──────────┐
    │ ts_sec │ ts_usec │ incl_len │ orig_len │
    │   4    │    4    │    4     │    4     │
    └────────┴─────────┴──────────┴──────────┘

magic 값이 바이트 순서를 알려 준다. 0xa1b2c3d4면 파일을 만든 기기와
읽는 기기의 바이트 순서가 같고, 뒤집혀 있으면 반대다. 0xa1b23c4d는
시간 단위가 마이크로초가 아니라 나노초라는 뜻이다.

network 필드가 링크 계층 종류(linktype)다. 이 값에 따라 패킷 데이터의
첫 바이트가 이더넷 헤더인지, BSD 루프백의 4바이트 AF 값인지, 아니면
곧바로 IP 헤더인지 갈린다. 06 폴더가 오버헤드를 셀 때 이 값이 중요하다.

    from tools.pcap import PcapFile
    with PcapFile("capture.pcap") as f:
        print(f.linktype_name)
        for ts, data, orig_len in f:
            ...
"""

import struct

# 자주 만나는 링크 계층 종류만 적는다. 전체 목록은 tcpdump.org/linktypes.html에 있다.
LINKTYPES = {
    0: "NULL",        # BSD 루프백. 앞에 4바이트 AF 값이 붙고 이더넷 헤더는 없다.
    1: "EN10MB",      # 이더넷. 14바이트 헤더.
    101: "RAW",       # 링크 헤더 없이 IP 헤더부터 시작한다.
    113: "LINUX_SLL", # 리눅스 cooked capture(-i any). 16바이트 가짜 헤더.
    276: "LINUX_SLL2",
}

# 각 링크 계층 헤더의 길이. 오버헤드를 셀 때 쓴다.
LINK_HEADER_LEN = {"NULL": 4, "EN10MB": 14, "RAW": 0, "LINUX_SLL": 16, "LINUX_SLL2": 20}

PCAPNG_MAGIC = 0x0A0D0D0A


class PcapError(Exception):
    pass


class PcapFile:
    """pcap 파일 하나를 열어 패킷을 차례로 돌려준다."""

    def __init__(self, path):
        self.path = path
        self._fh = open(path, "rb")
        head = self._fh.read(24)
        if len(head) < 24:
            raise PcapError(f"{path}: 파일이 너무 짧아 pcap 헤더를 읽지 못했다")

        magic = struct.unpack("<I", head[:4])[0]
        if magic == PCAPNG_MAGIC or struct.unpack(">I", head[:4])[0] == PCAPNG_MAGIC:
            raise PcapError(
                f"{path}: 이 파일은 pcapng다. 이 리더는 예전 pcap만 읽는다.\n"
                "  tcpdump -w 로 저장하면 pcap으로 나온다.\n"
                "  Wireshark에서는 '다른 이름으로 저장' → 'Wireshark/tcpdump/... - pcap'을 고른다.\n"
                "  이미 pcapng가 있으면 editcap -F pcap in.pcapng out.pcap 으로 바꾼다."
            )

        if magic == 0xA1B2C3D4:
            self.endian, self.nano = "<", False
        elif magic == 0xD4C3B2A1:
            self.endian, self.nano = ">", False
        elif magic == 0xA1B23C4D:
            self.endian, self.nano = "<", True
        elif magic == 0x4D3CB2A1:
            self.endian, self.nano = ">", True
        else:
            raise PcapError(f"{path}: pcap 파일이 아니다 (magic=0x{magic:08x})")

        fields = struct.unpack(self.endian + "HHiIII", head[4:])
        self.version = (fields[0], fields[1])
        self.snaplen = fields[4]
        self.linktype = fields[5]
        self.linktype_name = LINKTYPES.get(self.linktype, f"UNKNOWN({self.linktype})")
        self.link_header_len = LINK_HEADER_LEN.get(self.linktype_name)

    def __iter__(self):
        """(타임스탬프, 잡은 바이트, 원래 길이)를 차례로 돌려준다.

        incl_len은 실제로 파일에 담긴 길이이고 orig_len은 선 위에 있던
        원래 길이다. snaplen을 짧게 걸고 잡으면 둘이 달라진다.
        """
        hdr_fmt = self.endian + "IIII"
        while True:
            hdr = self._fh.read(16)
            if len(hdr) < 16:
                return
            ts_sec, ts_frac, incl_len, orig_len = struct.unpack(hdr_fmt, hdr)
            data = self._fh.read(incl_len)
            if len(data) < incl_len:
                return  # 캡처가 중간에 끊긴 파일
            ts = ts_sec + ts_frac / (1e9 if self.nano else 1e6)
            yield ts, data, orig_len

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def strip_link_header(linktype_name, data):
    """링크 계층 헤더를 걷어 내고 (헤더 길이, 상위 계층 바이트, 이더타입)을 돌려준다.

    이더타입은 0x0800이면 IPv4, 0x86DD면 IPv6, 0x0806이면 ARP다.
    링크 종류마다 상위 계층을 알려 주는 방식이 달라서 여기서 흡수한다.
    """
    if linktype_name == "EN10MB":
        if len(data) < 14:
            return 0, b"", None
        ethertype = struct.unpack("!H", data[12:14])[0]
        offset = 14
        while ethertype in (0x8100, 0x88A8):  # VLAN 태그가 붙어 있으면 건너뛴다
            if len(data) < offset + 4:
                return offset, b"", None
            ethertype = struct.unpack("!H", data[offset + 2:offset + 4])[0]
            offset += 4
        return offset, data[offset:], ethertype

    if linktype_name == "NULL":
        if len(data) < 4:
            return 0, b"", None
        # AF 값은 파일을 만든 기기의 바이트 순서로 적힌다. 둘 다 해 본다.
        af = struct.unpack("<I", data[:4])[0]
        if af not in (2, 24, 28, 30):
            af = struct.unpack(">I", data[:4])[0]
        ethertype = 0x0800 if af == 2 else 0x86DD
        return 4, data[4:], ethertype

    if linktype_name == "RAW":
        version = (data[0] >> 4) if data else 0
        return 0, data, 0x0800 if version == 4 else 0x86DD

    if linktype_name.startswith("LINUX_SLL"):
        n = LINK_HEADER_LEN[linktype_name]
        if len(data) < n:
            return 0, b"", None
        ethertype = struct.unpack("!H", data[14:16] if linktype_name == "LINUX_SLL" else data[0:2])[0]
        return n, data[n:], ethertype

    return 0, data, None
