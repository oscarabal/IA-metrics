"""OpenCode's models.dev catalog: the price and context limit of each model.

OpenCode 1.x cached it in `~/.cache/opencode/models.json`. OpenCode 2.x keeps it in its own database,
in the `kv` table (key `models-dev:v3:catalog`, the JSON of the catalog as text in `body`), with a new
shape for prices:

    1.x  "cost": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write": 3.75}
    2.x  "cost": {"text": {"input": {"price": 3, "cache": {"read": 0.3, "write": {"5m": 3.75, "1h": 6}}},
                           "output": {"price": 15}}}

`load()` returns the catalog in the 1.x shape whichever OpenCode wrote it: {provider: {"models": {model:
{"cost": {...}, "limit": {...}}}}}. models.json wins when it exists (OPENCODE_MODELS), so an install
that still has it, or a hand-made file, keeps working. Context and per-token text prices are all that
is kept; per-image or per-second prices and context tiers are ignored, as OpenCode itself does for
the base price.
"""
import json
import os
import sqlite3
import threading
import time

MODELS = os.environ.get("OPENCODE_MODELS", "/cache/models.json")
DB = os.environ.get("OPENCODE_DB", "/data/opencode.db")
KEY = "models-dev:v3:catalog"
# Seconds between two checks of the database for a newer catalog (OpenCode refreshes it every few hours)
CHECK_EVERY = int(os.environ.get("CATALOG_CHECK_SECONDS", "300"))

_state = {"stamp": None, "data": {}, "source": None, "checked": 0.0}
_lock = threading.Lock()


def _first(write):
    """OpenCode keeps one cache-write price: the first TTL listed (5 minutes before 1 hour)."""
    if isinstance(write, dict):
        return next(iter(write.values()), None)
    return write


def normalize_cost(cost):
    """A 2.x price ({"text": {...}}) in the 1.x shape; a 1.x price is returned as it is."""
    if not isinstance(cost, dict) or "text" not in cost:
        return cost
    text = cost.get("text") or {}
    inp, out = text.get("input") or {}, text.get("output") or {}
    cache = inp.get("cache") or {}
    write = _first(cache.get("write"))
    if write is None:
        write = _first((cache.get("explicit") or {}).get("write"))
    result = {"input": inp.get("price"), "output": out.get("price")}
    if cache.get("read") is not None:
        result["cache_read"] = cache.get("read")
    if write is not None:
        result["cache_write"] = write
    return result


def normalize(raw):
    """The catalog with every price in the 1.x shape and only cost and limit per model."""
    out = {}
    for prov, pdata in (raw or {}).items():
        models = {}
        for mid, mdata in ((pdata or {}).get("models") or {}).items():
            if not isinstance(mdata, dict):
                continue
            entry = {}
            if mdata.get("cost") is not None:
                entry["cost"] = normalize_cost(mdata["cost"])
            if isinstance(mdata.get("limit"), dict):
                entry["limit"] = mdata["limit"]
            models[mid] = entry
        out[prov] = {"models": models}
    return out


def _from_db():
    """(stamp, catalog) from opencode.db's kv table, or (None, None) when it is not there."""
    c = None
    for suffix in ("?mode=ro", "?immutable=1"):
        try:
            c = sqlite3.connect("file:" + DB + suffix, uri=True, timeout=5)
            row = c.execute("select value, time_updated from kv where key = ?", (KEY,)).fetchone()
            if row is None:  # a catalog from another source (a custom models.dev URL) is keyed KEY:<hash>
                row = c.execute("select value, time_updated from kv where key like ? and key not like '%:meta' "
                                "order by time_updated desc limit 1", (KEY + ":%",)).fetchone()
            break
        except sqlite3.Error:
            row = None
        finally:
            if c is not None:
                c.close()
                c = None
    if not row:
        return None, None
    value, updated = row
    try:
        wrapper = json.loads(value)
        body = wrapper.get("body") if isinstance(wrapper, dict) else None
        raw = json.loads(body) if isinstance(body, str) else body
    except ValueError:
        return None, None
    if not isinstance(raw, dict):
        return None, None
    return ("db", (wrapper.get("digest") if isinstance(wrapper, dict) else None) or updated), raw


def load():
    """The catalog in the 1.x shape (empty when OpenCode has none yet). Cached until it changes."""
    with _lock:
        try:
            mtime = os.path.getmtime(MODELS)
        except OSError:
            mtime = None
        if mtime is not None:
            if _state["stamp"] != ("file", mtime):
                with open(MODELS, encoding="utf-8") as f:
                    raw = json.load(f)
                _state.update(stamp=("file", mtime), data=normalize(raw), source="models.json")
            return _state["data"]
        if _state["source"] == "models.json":  # the file is gone: read the database now
            _state.update(stamp=None, data={}, source=None, checked=0.0)
        now = time.time()
        if now - _state["checked"] >= CHECK_EVERY:
            _state["checked"] = now
            stamp, raw = _from_db()
            if stamp is not None and stamp != _state["stamp"]:
                _state.update(stamp=stamp, data=normalize(raw), source="opencode.db")
        return _state["data"]


def stamp():
    """Changes whenever load() returns a different catalog."""
    load()
    return _state["stamp"]


def available():
    """True when a catalog was found (models.json or opencode.db)."""
    return bool(load())


def source():
    """Where the catalog was read from: "models.json", "opencode.db" or None."""
    load()
    return _state["source"]


def reset():
    """Forget the cached catalog (tests)."""
    with _lock:
        _state.update(stamp=None, data={}, source=None, checked=0.0)
