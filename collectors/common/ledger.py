"""Query engine and HTTP API over a collector's usage ledger (ADR 0002).

A collector registers *datasets*: functions that return a list of rows (dicts). Every row has `ts`
(Unix ms) and `project`; the rest are dimensions (strings) or measures (numbers). The API filters,
groups and sums them for Grafana's Infinity datasource:

    GET /data                                  -> datasets, with their dimensions and measures
    GET /data/<dataset>?from=&to=&project=&group=day,model&sort=-cost&limit=10
    GET /data/<dataset>/values?field=project   -> distinct values, for dashboard variables

Parameters
    from, to      Unix ms (Grafana's ${__from} and ${__to}); inclusive. Default: all history.
    project       one or more names (repeated or separated by "," or "|"); "All", "$__all" and ".*"
                  mean every project.
    f.<field>     keep only rows whose <field> is one of the values given (same separators).
    nf.<field>    drop the rows whose <field> is one of the values given.
    group         dimensions to group by. "hour", "day", "week" and "month" bucket `ts` in the time
                  zone TZ (default Europe/Madrid) and also return `time`, the bucket's start in ms.
                  "auto" picks the bucket from the time range (from/to): about `points` buckets (default
                  40), from 1 minute to a month, aligned in TZ. It returns `auto` (the bucket's label),
                  `interval` («15 min», «1 h», «día»...) and `time`, never earlier than `from`, so the
                  first bucket of a short range still falls inside the chart.
                  Without `group` the answer is one row with the totals.
    points        with group=auto, how many buckets to aim for (1-1000).
    measures      measures to return (default: all). `n` is always available: the number of rows.
    sort, limit   order by a returned field ("-" for descending) and cut the list.
    top           "<dimension>:<N>[:<measure>]": keep the N values of the dimension with the highest
                  total of the measure (default: the first one requested); the others are dropped,
                  or merged under the name given in `other`.
    calc          "name:expression;name:expression": fields computed after summing, from the measures
                  and from total_<measure> (the total over every returned row), with + - * / and
                  parentheses. A division by zero gives null. Example: share:cost/total_cost
    nonzero       drop the rows where this field is 0 or null.
    distinct      dimensions whose distinct values to count, returned as distinct_<dimension>
                  (for example the sessions with activity: distinct=session).
    mask          dimensions whose text is replaced by asterisks before it leaves the collector (for
                  example mask=prompt, from a dashboard's «show / hide» switch); "none" masks nothing.
    var-<name>    what Grafana's ${<name>:queryparam} sends (URL-encoded): var-project filters project and
                  var-sessions filters session; "All", "$__all" and ".*" mean no filter.

Measures are summed; ratios (cache hit, cost per message...) are left to Grafana, which computes
them from these sums. Floats are rounded to 6 decimals.
"""
import ast
import datetime
import json
import os
import re
import threading
import time
import urllib.parse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

TIME_GROUPS = ("hour", "day", "week", "month", "auto")
# group=auto: bucket sizes to choose from (ms, unit or None for a fixed size, label for the panels)
MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000
AUTO_STEPS = ((MINUTE, None, "1 min"), (2 * MINUTE, None, "2 min"), (5 * MINUTE, None, "5 min"), (10 * MINUTE, None, "10 min"),
              (15 * MINUTE, None, "15 min"), (30 * MINUTE, None, "30 min"), (HOUR, None, "1 h"), (2 * HOUR, None, "2 h"),
              (3 * HOUR, None, "3 h"), (6 * HOUR, None, "6 h"), (12 * HOUR, None, "12 h"), (DAY, "day", "día"),
              (7 * DAY, "week", "semana"), (30 * DAY, "month", "mes"))
AUTO_POINTS = 40
# Tool error classes that are not the model's fault (a permission rule, the user saying no, an
# interruption): OpenCode's "avoidable_errors" leaves them out. Claude Code uses its own, wider set
# (coach/errors.py NOT_AVOIDABLE), which adds classes only it has (plans, hooks, commands).
UNAVOIDABLE_ERRORS = frozenset(("permission_rule", "user_rejected", "aborted"))
_ALL = {"", "all", "$__all", ".*", "*"}
_SPLIT = re.compile(r"[,|]")


def tz():
    name = os.environ.get("TZ") or "Europe/Madrid"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return datetime.timezone.utc


def bucket(ts_ms, unit, zone=None):
    """(label, start ms) of the hour/day/week/month that contains `ts_ms`, in the local time zone."""
    zone = zone or tz()
    t = datetime.datetime.fromtimestamp(ts_ms / 1000, zone)
    if unit == "hour":
        start = t.replace(minute=0, second=0, microsecond=0)
        label = start.strftime("%Y-%m-%d %H:00")
    elif unit == "day":
        start = t.replace(hour=0, minute=0, second=0, microsecond=0)
        label = start.strftime("%Y-%m-%d")
    elif unit == "week":  # ISO week, labelled by its Monday
        monday = (t - datetime.timedelta(days=t.weekday())).date()
        start = datetime.datetime(monday.year, monday.month, monday.day, tzinfo=zone)
        label = monday.isoformat()
    elif unit == "month":
        start = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = start.strftime("%Y-%m")
    else:
        raise ValueError(unit)
    return label, int(start.timestamp() * 1000)


def auto_step(since, until, points=AUTO_POINTS):
    """(ms, unit, label) of the smallest bucket that splits since..until into at most about `points` buckets."""
    want = max(until - since, MINUTE) / max(points, 1)
    return next((s for s in AUTO_STEPS if s[0] >= want), AUTO_STEPS[-1])


def auto_bucket(ts_ms, step, zone=None):
    """(label, start ms) of the group=auto bucket of `step` (from auto_step) that contains `ts_ms`."""
    ms, unit, _label = step
    if unit:
        return bucket(ts_ms, unit, zone)
    zone = zone or tz()
    off = int(datetime.datetime.fromtimestamp(ts_ms / 1000, zone).utcoffset().total_seconds() * 1000)
    start = (ts_ms + off) // ms * ms - off   # aligned in local time: 3-hour buckets start at 00:00, 03:00...
    return datetime.datetime.fromtimestamp(start / 1000, zone).strftime("%Y-%m-%d %H:%M"), int(start)


def _values(query, key):
    out = []
    for v in query.get(key, []):
        out.extend(x.strip() for x in _SPLIT.split(v))
    return [x for x in out if x]


def _int(query, key):
    try:
        return int(float(query[key][0]))
    except (KeyError, ValueError, IndexError):
        return None


_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def compile_calc(expr):
    """A safe evaluator of + - * / over names and numbers. Raises ValueError on anything else."""
    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError as e:
        raise ValueError("expresión no válida: %s" % expr) from e

    def check(n):
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            check(n.left), check(n.right)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            check(n.operand)
        elif isinstance(n, ast.Name) or isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            pass
        else:
            raise ValueError("expresión no permitida: %s" % expr)
    check(tree)

    def ev(n, env):
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left, env), ev(n.right, env)
            if a is None or b is None:
                return None
            if isinstance(n.op, ast.Div) and b == 0:
                return None
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand, env)
            return None if v is None else -v
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise ValueError("campo desconocido en la expresión: %s" % n.id)
            return env[n.id]
        return n.value
    return lambda env: ev(tree, env)


MASK_CHAR = "*"
MASK_MAX = 40


def mask_text(value):
    """Asterisks instead of the text, at most MASK_MAX of them, so the table keeps its shape."""
    text = str(value or "")
    return MASK_CHAR * min(len(text), MASK_MAX) if text.strip() else text


def describe(rows):
    """Dimensions and measures of a dataset, from its rows."""
    dims, measures = set(), set()
    for r in rows[:500]:
        for k, v in r.items():
            if k == "ts":
                continue
            (measures if isinstance(v, (int, float)) and not isinstance(v, bool) else dims).add(k)
    return sorted(dims), sorted(measures | {"n"})


def query(rows, q):
    """Filter, group and sum `rows` (see the module docstring). `q` is a parse_qs dict."""
    since, until = _int(q, "from"), _int(q, "to")
    projects = {p for p in _values(q, "project") + _values(q, "var-project") if p.lower() not in _ALL}
    filters = {k[2:]: set(_values(q, k)) for k in q if k.startswith("f.")}
    sessions = {v for v in _values(q, "var-sessions") if v.lower() not in _ALL}
    if sessions:
        filters["session"] = sessions
    filters = {k: v for k, v in filters.items() if v and not (v & {"$__all", "All"})}
    excluded = {k[3:]: set(_values(q, k)) for k in q if k.startswith("nf.")}
    group = _values(q, "group")
    distinct = _values(q, "distinct")
    dims, measures = describe(rows)
    if not rows:  # nothing yet (a collector that has just started, a tool never used): an empty table, not an error
        return [] if group else [dict({m: 0 for m in (_values(q, "measures") or ["n"])}, **{"distinct_" + d: 0 for d in distinct})]
    wanted = _values(q, "measures") or measures
    unknown = [g for g in group if g not in TIME_GROUPS and g not in dims]
    if unknown:
        raise ValueError("no se puede agrupar por: %s (dimensiones: %s)" % (", ".join(unknown), ", ".join(dims)))
    calcs = []
    for item in ";".join(q.get("calc", [])).split(";"):
        if item.strip():
            name, _, expr = item.partition(":")
            if not expr:
                raise ValueError("calc necesita nombre:expresión: %s" % item)
            calcs.append((name.strip(), compile_calc(expr.strip())))
    zone = tz()

    def keep(r):
        ts = r.get("ts") or 0
        if since is not None and ts < since or until is not None and ts > until:
            return False
        if projects and r.get("project") not in projects:
            return False
        if any(str(r.get(k)) not in v for k, v in filters.items()):
            return False
        return not any(str(r.get(k)) in v for k, v in excluded.items())
    selected = [r for r in rows if keep(r)]
    masked = [f for f in _values(q, "mask") if f.lower() != "none"]
    if masked:  # before grouping and before anything is sent: the text never leaves the collector
        selected = [dict(r, **{f: mask_text(r.get(f)) for f in masked if f in r}) for r in selected]

    # top: rank the values of one dimension by a measure, over the whole selection
    top_dim, rename, other = None, {}, (q.get("other") or [None])[0]
    if q.get("top"):
        spec = q["top"][0].split(":")
        top_dim = spec[0]
        if top_dim not in dims:
            raise ValueError("top: dimensión desconocida %s" % top_dim)
        n = int(spec[1]) if len(spec) > 1 and spec[1].isdigit() else 10
        by = spec[2] if len(spec) > 2 else next((m for m in wanted if m != "n"), "n")
        totals = {}
        for r in selected:
            totals[r.get(top_dim, "")] = totals.get(r.get(top_dim, ""), 0) + (1 if by == "n" else (r.get(by) or 0))
        keep_vals = {v for v, _t in sorted(totals.items(), key=lambda x: -x[1])[:n]}
        rename = {v: (v if v in keep_vals else other) for v in totals}

    step = None
    if "auto" in group:
        stamps = [r.get("ts") or 0 for r in selected]
        lo = since if since is not None else min(stamps, default=0)
        hi = until if until is not None else max(stamps, default=lo)
        points = _int(q, "points") or AUTO_POINTS
        step = auto_step(lo, hi, min(max(points, 1), 1000))

    out, seen = {}, {}
    for r in selected:
        if top_dim is not None:
            r = dict(r)
            r[top_dim] = rename.get(r.get(top_dim, ""))
            if r[top_dim] is None:
                continue
        ts = r.get("ts") or 0
        key, extra = [], {}
        for g in group:
            if g == "auto":
                label, start = auto_bucket(ts, step, zone)
                key.append(label)
                # never before the range: the first bucket of a short range stays inside the chart
                extra["auto"], extra["interval"] = label, step[2]
                extra["time"] = max(start, since) if since is not None else start
            elif g in TIME_GROUPS:
                label, start = bucket(ts, g, zone)
                key.append(label)
                extra[g], extra["time"] = label, start
            else:
                key.append(r.get(g, ""))
        key = tuple(key)
        acc = out.get(key)
        if acc is None:
            acc = out[key] = dict(zip(group, key), **extra)
            for m in wanted:
                acc[m] = 0
        for m in wanted:
            acc[m] += 1 if m == "n" else (r.get(m) or 0)
        for dname in distinct:
            seen.setdefault((key, dname), set()).add(r.get(dname))
    for key, acc in out.items():
        for dname in distinct:
            acc["distinct_" + dname] = len(seen.get((key, dname), ()))
    result = list(out.values())
    if not group and not result:  # totals of an empty range are zeros, not an empty table
        result = [dict({m: 0 for m in wanted}, **{"distinct_" + d: 0 for d in distinct})]
    if calcs:
        totals = {"total_" + m: sum(r.get(m) or 0 for r in result) for m in wanted}
        for r in result:
            env = dict(totals, **r)
            for name, fn in calcs:
                r[name] = env[name] = fn(env)
    nonzero = (q.get("nonzero") or [None])[0]
    if nonzero:
        result = [r for r in result if r.get(nonzero)]
    for r in result:
        for k, v in r.items():
            if isinstance(v, float):
                r[k] = round(v, 6)
    sort = (q.get("sort") or [""])[0]
    if sort:
        desc, field = sort.startswith("-"), sort.lstrip("-")
        result.sort(key=lambda r: (r.get(field) is None, r.get(field)), reverse=desc)
    elif group:
        result.sort(key=lambda r: tuple(str(r.get(g, "")) for g in group))
    limit = _int(q, "limit")
    return result[:limit] if limit else result


def distinct(rows, field):
    return sorted({str(r.get(field)) for r in rows if r.get(field) not in (None, "")})


class Ledger:
    """The datasets of one collector, with a short cache so several panels share one build."""

    def __init__(self, ttl=15):
        self._sources = {}
        self._cache = {}
        self._lock = threading.Lock()
        self.ttl = ttl

    def register(self, name, build):
        self._sources[name] = build

    def rows(self, name):
        with self._lock:
            hit = self._cache.get(name)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        rows = self._sources[name]()
        with self._lock:
            self._cache[name] = (time.time(), rows)
        return rows

    def handle(self, path, query_string):
        """(status, payload) for a /data request."""
        q = urllib.parse.parse_qs(query_string, keep_blank_values=False)
        parts = [p for p in path.split("/") if p][1:]  # drop "data"
        if not parts:
            info = {}
            for name in sorted(self._sources):
                dims, measures = describe(self.rows(name))
                info[name] = {"dimensions": dims, "measures": measures}
            return 200, info
        name = parts[0]
        if name not in self._sources:
            return 404, {"error": "no existe el conjunto de datos %r" % name, "datasets": sorted(self._sources)}
        rows = self.rows(name)
        try:
            if len(parts) > 1 and parts[1] == "values":
                field = (q.get("field") or ["project"])[0]
                return 200, [{"value": v} for v in distinct(rows, field)]
            return 200, query(rows, q)
        except ValueError as e:
            return 400, {"error": str(e)}


def respond(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
