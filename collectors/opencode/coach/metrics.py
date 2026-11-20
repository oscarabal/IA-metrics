"""The coach's reading of opencode.db, shared by the improvement report and the /data API.

The background thread reads the messages, sessions, tool calls and compactions every SERIES_EVERY
seconds (or sooner when a findings panel finds the data old) and keeps them here, so neither a
panel nor a scrape reads the database (see `snapshot`). The per-day and per-week series this module
used to publish are gone (ADR 0002): the dashboards read /data.

Until the tool index is ready nothing is published but `coach_index_ready` 0.
"""
import threading
import time

from . import report
from .index import INDEX

SERIES_EVERY = 120             # seconds between two readings of the database for the series

# Everything is computed in the exporter's background thread and cached here: a scrape only
# copies text, so it costs no more than before this module existed. On a Windows bind mount
# the extra database reads made scrapes pass Prometheus' 10 s timeout.
_state = {"series_updated": 0, "loaded": None, "loaded_at": 0}
_lock = threading.Lock()
_wake = threading.Event()   # set by a findings panel that finds the data old, to read it again sooner


def refresh(conn, helpers, force=False):
    """Read the database when due, or now with `force`. Called from the background thread."""
    if not INDEX.ready:
        return
    if not force and time.time() - _state["series_updated"] < SERIES_EVERY:
        return
    read_at = time.time()
    loaded = report.load(conn, helpers, refresh=False)  # the thread has just refreshed the index
    with _lock:
        _state.update(series_updated=time.time(), loaded=loaded, loaded_at=read_at)


def snapshot():
    """The data of the last reading and when it started, or (None, 0) before the first one."""
    with _lock:
        return _state["loaded"], _state["loaded_at"]


def request_refresh():
    """Ask the background thread to read the database now instead of at its next turn."""
    _wake.set()


def wait(seconds):
    """Sleep the background thread until its next turn or a request. True if it was a request."""
    woken = _wake.wait(seconds)
    _wake.clear()
    return woken


def lines(*_ignored):
    """What a scrape publishes. Reads nothing from the database."""
    with _lock:
        s_upd = _state["series_updated"]
    out = []
    add = out.append
    add("# TYPE coach_index_ready gauge")
    add("coach_index_ready %d" % (1 if INDEX.ready else 0))
    add("# TYPE coach_series_updated_timestamp_seconds gauge")
    add("coach_series_updated_timestamp_seconds %s" % round(s_upd))
    return out
