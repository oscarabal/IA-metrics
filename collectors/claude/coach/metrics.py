"""Background work of the coach and the Prometheus series it publishes.

Everything is computed in a background thread and cached: a scrape only copies text.

The thread, every round:
- saves the request costs the index has read from Loki into the store (so they survive),
- archives the sessions of the index (ADR 0002) and applies the store's retention,
- every 10 minutes, recomputes the findings of the improvement report for 7, 30 and 90 days.

The per-day and per-week series it used to publish are gone (ADR 0002): the dashboards read /data.
"""
import threading
import time
from collections import Counter

import index  # noqa: E402  (ROOT)
from . import report
from . import store as coach_store

ROUND = 30
FINDINGS_EVERY = 600
WINDOWS = (7, 30, 90)

_state = {"by_window": {}, "findings_at": 0}
_lock = threading.Lock()


def _lab(**kw):
    return ",".join('%s="%s"' % (k, str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")) for k, v in kw.items())


def start(ix):
    st = coach_store.get()
    try:
        st.restore(ix)  # costs from earlier runs, before the index starts reading Loki again
    except Exception:
        pass
    try:  # sessions whose conversation file Claude Code has deleted since (ADR 0002)
        st.restore_sessions(ix, index.ROOT)
    except Exception:
        pass
    threading.Thread(target=_loop, args=(ix,), daemon=True).start()


def _loop(ix):
    while True:
        try:
            _round(ix)
        except Exception as e:  # the next round retries; scrapes keep serving the cache
            print("AVISO: fallo en el trabajo de fondo del informe (%s)." % type(e).__name__, flush=True)
        time.sleep(ROUND)


def _round(ix):
    st = coach_store.get()
    st.save_requests(ix)
    st.archive_sessions(ix)
    st.maintain()
    if not ix.done:
        return
    if time.time() - _state["findings_at"] < FINDINGS_EVERY:
        return
    data = report.snapshot(ix)
    ms = int(time.time() * 1000)
    by_window = {}
    for w in WINDOWS:
        r = report.build(ix, ms - w * 86400000, ms, "w%d" % w, data=data)
        by_window[w] = [(f["detector"], f["severity"], f.get("impact_usd") or 0.0) for f in r["findings"]]
    with _lock:
        _state.update(by_window=by_window, findings_at=time.time())


def lines():
    """What a scrape publishes; reads nothing but the cache."""
    with _lock:
        by_window = dict(_state["by_window"])
        f_at = _state["findings_at"]
    out = []
    add = out.append
    add("# TYPE claude_coach_findings gauge")
    add("# TYPE claude_coach_finding_impact_usd gauge")
    for w, items in by_window.items():
        count, impact = Counter(), Counter()
        for det, sev, usd in items:
            count[(det, sev)] += 1
            impact[det] += usd
        for (det, sev), n in count.items():
            add("claude_coach_findings{%s} %d" % (_lab(window=w, detector=det, rule=report.RULES.get(det, det), severity=sev), n))
        for det, v in impact.items():
            add("claude_coach_finding_impact_usd{%s} %s" % (_lab(window=w, detector=det, rule=report.RULES.get(det, det)), round(v, 4)))
    add("# TYPE claude_coach_findings_updated_timestamp_seconds gauge")
    add("claude_coach_findings_updated_timestamp_seconds %d" % f_at)
    add("# TYPE claude_coach_store_persistent gauge")
    add("claude_coach_store_persistent %d" % (1 if coach_store.get().persistent else 0))
    return out
