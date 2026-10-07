#!/usr/bin/env python3
"""GraphQL API 서버 (가르치기 위한 최소 구현).

REST와 갈리는 지점은 하나다. **무엇을 받을지 클라이언트가 정한다.**

    REST      GET /sensors/living-room      →  서버가 정한 필드가 모두 온다
    GraphQL   { sensor { temperature } }    →  temperature 만 온다

엔드포인트도 하나뿐이다. 자원마다 URL을 파는 REST와 달리 /graphql 한 곳에
질의를 적어 보낸다. 그래서 HTTP 메서드도 대개 POST 하나만 쓴다. 캐시와
상태 코드를 HTTP에 맡기던 REST의 이점을 여기서 상당 부분 내려놓는 셈이다.

**이 구현은 GraphQL 명세를 다 따르지 않는다.** 변수, 조각(fragment), 별칭,
지시어, 타입 검사를 뺀 가르치기용 부분집합이다. 실무에서는 graphql-core나
Strawberry 같은 라이브러리를 쓴다. 여기서 보려는 것은 "질의가 응답 모양을
정한다"는 생각 하나다.

    python3 server.py
"""

import argparse
import json
import pathlib
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common.store import get, set_value  # noqa: E402

SCHEMA = """
type Sensor {
  id: ID!
  temperature: Float!
  unit: String!
  ts: Float!
}

type Query {
  sensor(id: ID!): Sensor
}

type Mutation {
  setTemperature(id: ID!, value: Float!): Sensor
}
"""

FIELD_MAP = {"id": "sensor", "temperature": "temperature", "unit": "unit", "ts": "ts"}


def parse_selection(query):
    """가장 바깥 { } 안에서 루트 이름, 인자, 고른 필드를 뽑는다.

    정규식으로 자르는 조잡한 파서다. 진짜 GraphQL 파서는 토큰을 읽어 구문
    나무를 만든다. 여기서는 '질의가 응답 모양을 정한다'만 보이면 된다.
    """
    is_mutation = query.strip().startswith("mutation")
    m = re.search(r"(\w+)\s*(\([^)]*\))?\s*\{([^}]*)\}", query[query.find("{") + 1:])
    if not m:
        return None
    root, raw_args, body = m.group(1), m.group(2) or "", m.group(3)

    args = {}
    for key, value in re.findall(r'(\w+)\s*:\s*("?[^,")]*"?)', raw_args):
        args[key] = value.strip().strip('"')

    fields = [f for f in re.split(r"[\s,]+", body.strip()) if f]
    return {"mutation": is_mutation, "root": root, "args": args, "fields": fields}


def execute(query):
    """질의를 실행한다. 고른 필드만 담아 돌려준다."""
    parsed = parse_selection(query)
    if not parsed:
        return {"errors": [{"message": "질의를 읽지 못했다"}]}

    if parsed["mutation"]:
        if parsed["root"] != "setTemperature":
            return {"errors": [{"message": f"그런 뮤테이션이 없다: {parsed['root']}"}]}
        try:
            record = set_value(float(parsed["args"].get("value", 0)))
        except (ValueError, OverflowError):
            return {"errors": [{"message": "value가 숫자가 아니다"}]}
    else:
        if parsed["root"] != "sensor":
            return {"errors": [{"message": f"그런 질의가 없다: {parsed['root']}"}]}
        record = get()

    unknown = [f for f in parsed["fields"] if f not in FIELD_MAP]
    if unknown:
        return {"errors": [{"message": f"Sensor에 그런 필드가 없다: {', '.join(unknown)}"}]}

    # 클라이언트가 고른 필드만 담는다. 이것이 GraphQL의 요점이다.
    data = {field: record[FIELD_MAP[field]] for field in parsed["fields"]}
    return {"data": {parsed["root"]: data}}


class Handler(BaseHTTPRequestHandler):
    server_version = "graphql-api/1.0"

    def log_message(self, fmt, *args):
        if self.server.verbose:
            print(f"[서버] {fmt % args}", flush=True)

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/graphql/schema":
            body = SCHEMA.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(405, {"errors": [{"message": "GraphQL은 POST /graphql 로 부른다"}]})

    def do_POST(self):
        if self.path != "/graphql":
            self._send(404, {"errors": [{"message": "엔드포인트는 /graphql 하나다"}]})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            query = payload["query"]
        except (json.JSONDecodeError, KeyError):
            self._send(400, {"errors": [{"message": "본문에 query가 있어야 한다"}]})
            return

        if self.server.verbose:
            print(f"[서버] 질의: {query.strip()}", flush=True)
        result = execute(query)
        # GraphQL은 오류가 나도 HTTP 200으로 답하는 것이 보통이다.
        # 오류는 본문의 errors 에 담는다. HTTP 상태 코드를 쓰지 않는 셈이다.
        self._send(200, result)


def main():
    ap = argparse.ArgumentParser(description="GraphQL API 서버 (가르치기용 부분집합)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9300)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.verbose = not args.quiet
    print(f"[서버] http://{args.host}:{args.port}/graphql (POST)", flush=True)
    print(f"[서버] 스키마: http://{args.host}:{args.port}/graphql/schema", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[서버] 멈춘다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
