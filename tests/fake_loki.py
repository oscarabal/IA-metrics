"""A minimal Loki that answers the collector's two kinds of query from the fixture telemetry."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fixtures


def _api_request_streams():
    by_req = {r[2]: (n, r) for n, r in enumerate(fixtures.CC_ASSISTANT)}
    streams = []
    for req, cost in fixtures.CC_TELEMETRY_COST.items():
        n, (sid, ts, _req, model, (i, o, cr, cc), _side) = by_req[req]
        streams.append({"stream": {"event_name": "api_request", "request_id": req, "cost_usd": str(cost),
                                   "model": model, "session_id": sid, "prompt_id": "p%d" % n, "query_source": "main",
                                   "effort": "high", "output_tokens": str(o)},
                        "values": [[str(ts * 1_000_000), "{}"]]})
    return streams


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        query = q.get("query", [""])[0]
        if 'event_name="api_request"' in query and "direction" in q:
            result = {"resultType": "streams", "result": _api_request_streams()}
        elif "direction" in q:
            result = {"resultType": "streams", "result": []}
        else:
            result = {"resultType": "matrix", "result": []}
        body = json.dumps({"status": "success", "data": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % httpd.server_address[1]
