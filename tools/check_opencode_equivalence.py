"""Compare, on a real opencode.db, the legacy per-day Prometheus series with the /data API (ADR 0002).

    python tools/check_opencode_equivalence.py <path to opencode.db>

Read-only: copy the database (with its -wal and -shm files) somewhere else first if OpenCode is running.
Prints only totals, key counts and differences; never session titles or message text.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "collectors", "opencode"), os.path.join(ROOT, "collectors"), os.path.join(ROOT, "tests")]
sys.dont_write_bytecode = True

db = sys.argv[1]
os.environ.update(OPENCODE_DB=db, OPENCODE_MODELS="/nonexistent/models.json", OPENCODE_COMMANDS_DIR="/nonexistent",
                  OPENCODE_QUOTA_DIR="/nonexistent", TZ="UTC")
import helpers  # noqa: E402
import exporter  # noqa: E402
import ledger_source  # noqa: E402
from common import ledger  # noqa: E402
from coach import index as coach_index, metrics as coach_metrics  # noqa: E402

t = time.time()
exporter.refresh_skill_calls()
c = exporter.connect()
coach_index.INDEX.refresh(c)
coach_metrics.refresh(c, exporter, exporter.WEEKS, force=True)
c.close()
print("lectura inicial: %.1f s" % (time.time() - t))
t = time.time()
series = helpers.parse_metrics(exporter.collect())
print("scrape antiguo: %.1f s, %d series (%d por día/semana)" % (
    time.time() - t, len(series), sum(1 for n, _l, _v in series if n.startswith(("opencode_day_", "opencode_weekly_")))))

PAIRS = [
    ("opencode_day_cost_usd", ("day", "provider", "model", "agent", "project"), "usage", "cost", None),
    ("opencode_day_messages", ("day", "provider", "model", "agent", "project"), "usage", "messages", None),
    ("opencode_day_sessions", ("day", "project"), "sessions", "sessions", None),
    ("opencode_day_tool_calls", ("day", "tool", "model", "project"), "tools", "calls", None),
    ("opencode_day_tool_errors", ("day", "tool", "error_class", "model", "project"), "tools", "errors", None),
    ("opencode_day_compactions", ("day", "project"), "compactions", "compactions", None),
    ("opencode_day_aborted", ("day", "agent", "project"), "usage", "aborted", None),
    ("opencode_day_skill_activations", ("day", "kind", "skill", "project", "result"), "skills", "activations", None),
    ("opencode_day_skill_cost_usd", ("day", "kind", "skill", "project"), "skills", "cost", None),
    ("opencode_weekly_cost_usd", ("week", "project"), "usage", "cost", None),
    ("opencode_weekly_agent_messages", ("week", "agent", "project"), "usage", "messages", None),
    ("opencode_weekly_tool_calls", ("week", "tool", "project"), "tools", "calls", None),
] + [("opencode_day_tokens", ("day", "provider", "model", "agent", "project"), "usage", t_, {"type": t_})
     for t_ in ("input", "output", "reasoning", "cache_read", "cache_write")]

bad = 0
t = time.time()
for name, labels, dataset, measure, lf in PAIRS:
    want = {}
    for n, lab, v in series:
        if n == name and all(lab.get(k) == w for k, w in (lf or {}).items()):
            key = tuple(lab[x] for x in labels)
            want[key] = want.get(key, 0) + v
    rows = ledger.query(ledger_source.LEDGER.rows(dataset), {"group": [",".join(labels)]})
    got = {tuple(str(r[g]) for g in labels): r[measure] for r in rows}
    if name.startswith("opencode_weekly_"):  # legacy weekly series cover the last WEEKS weeks only
        got = {k: v for k, v in got.items() if k in want or not v}
    want = {k: v for k, v in want.items() if v}
    got = {k: v for k, v in got.items() if v}
    keys = set(want) | set(got)
    diff = [(k, want.get(k, 0), got.get(k, 0)) for k in keys if abs(want.get(k, 0) - got.get(k, 0)) > 1e-6 * max(1, abs(want.get(k, 0)))]
    status = "OK " if not diff else "DIF"
    bad += bool(diff)
    print("%s %-40s claves=%5d total antiguo=%16.6f api=%16.6f diferencias=%d" % (
        status, name + ("[%s]" % lf["type"] if lf else ""), len(keys), sum(want.values()), sum(got.values()), len(diff)))
    for k, a, b in sorted(diff, key=lambda x: -abs(x[1] - x[2]))[:3]:
        print("      p.ej. %s antiguo=%s api=%s" % (k[:1] + ("…",), a, b))
print("comparación: %.1f s" % (time.time() - t))
t = time.time()
for _ in range(5):
    ledger_source.LEDGER._cache.clear()
    ledger.query(ledger_source.LEDGER.rows("usage"), {"group": ["day,model"], "from": ["0"]})
print("consulta típica de un panel (sin caché): %.0f ms" % ((time.time() - t) / 5 * 1000))
print("RESULTADO:", "todo coincide" if not bad else "%d series con diferencias" % bad)
sys.exit(1 if bad else 0)
