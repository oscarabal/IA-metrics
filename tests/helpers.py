"""Shared test helpers: environment, Prometheus text parsing and an HTTP server on a free port."""
import http.client
import json
import os
import re
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTORS = os.path.join(ROOT, "collectors")
TESTS = os.path.dirname(os.path.abspath(__file__))

_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{(.*)\})?\s+(\S+)$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def use_collector(name):
    """Put one collector (and collectors/common) first on sys.path, as the container does."""
    sys.path[:0] = [os.path.join(COLLECTORS, name), COLLECTORS, TESTS]
    sys.dont_write_bytecode = True


def tmpdir():
    return tempfile.mkdtemp(prefix="iametrics-")


def parse_metrics(text):
    """[(name, {labels}, value)] from Prometheus exposition text."""
    out = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise AssertionError("línea de métricas no válida: %r" % line)
        labels = {k: v.replace('\\"', '"').replace("\\\\", "\\") for k, v in _LABEL.findall(m.group(3) or "")}
        out.append((m.group(1), labels, float(m.group(4))))
    return out


def total(series, name, **match):
    return sum(v for n, lab, v in series if n == name and all(lab.get(k) == w for k, w in match.items()))


class Server:
    """Runs a collector's Handler on 127.0.0.1 and a free port."""

    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get(self, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.putrequest("GET", path, skip_host=True)
        if host is not False:
            c.putheader("Host", host or "localhost:%d" % self.port)
        c.endheaders()
        r = c.getresponse()
        body = r.read().decode("utf-8")
        c.close()
        return r.status, body

    def json(self, path):
        status, body = self.get(path)
        if status != 200:
            raise AssertionError("%s -> %s: %s" % (path, status, body[:300]))
        return json.loads(body)

    def close(self):
        self.httpd.shutdown()


# ---------------------------------------------------------------------- dashboards against the API
def dashboard_queries(path, host_prefix, start_ms, end_ms):
    """(panel title, local path, fields the panel's transformations and options use) for each Infinity
    query of a dashboard that targets `host_prefix`, with Grafana's variables filled in as Grafana would."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    customs = {v["name"]: str((v.get("current") or {}).get("value", "")) for v in d.get("templating", {}).get("list", [])
               if v.get("type") == "custom"}

    def walk(p):
        yield p
        for c in p.get("panels", []):
            yield from walk(c)
    for top in d["panels"]:
        for p in walk(top):
            used, renamed = set(), False
            for t in p.get("transformations", []):
                o = t.get("options", {})
                if t.get("id") == "organize":
                    if renamed:  # later renames act on names that earlier transformations produced
                        continue
                    renamed = True
                # "Value #X", "message" and "Time" come from Prometheus queries in mixed panels
                used.update(k for k in o.get("renameByName", {}) if not k.startswith("Value #") and k not in ("message", "Time") and "\\" not in k)
                used.update(k for k in o.get("indexByName", {}) if not k.startswith("Value #") and k not in ("message", "Time") and "\\" not in k)
                for key in ("valueField", "columnField", "rowField", "byField"):
                    if o.get(key):
                        used.add(o[key])
            m = re.match(r"^/\^(\w+)\$/$", (p.get("options", {}).get("reduceOptions", {}) or {}).get("fields", "") or "")
            if m:
                used.add(m.group(1))
            used.update(f for f in ((p.get("options", {}).get("footer") or {}).get("fields") or []) if not f.startswith("Value #"))
            for t in p.get("targets", []):
                url = t.get("url") or ""
                if not url.startswith(host_prefix):
                    continue
                local = url[len(host_prefix):]
                local = (local.replace("${__from}", str(start_ms)).replace("${__to}", str(end_ms))
                         .replace("${project:queryparam}", "var-project=%24__all").replace("${project:csv}", "%24__all")
                         .replace("${sessions:queryparam}", "var-sessions=.*"))
                for name, value in customs.items():
                    local = local.replace("${%s}" % name, value)
                out.append((p.get("title"), local, used))
    return out
