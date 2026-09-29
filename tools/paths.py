"""하위 폴더의 스크립트가 tools 패키지를 찾게 해 주는 조각.

각 스크립트 맨 위에서 이렇게 쓴다.

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from tools.pcap import PcapFile

폴더가 두 겹 아래(04-application/http 등)면 parents[2]로 적는다.
"""
