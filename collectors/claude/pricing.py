"""Estimated cost of one Claude API request from its token usage (ADR 0002).

Used only when Claude Code's telemetry did not report the request's cost (the stack was down, the
telemetry was off, or the request is older than the telemetry). The table is prices.json; see its
_doc for the rules. A model that is not in the table is looked up in a copy of models.dev
(MODELS_DEV_FILE, downloaded by map.py): its price there has no periods, fast mode or US-only
multiplier, so prices.json stays the main source. Without either it gives None ("missing"), never 0.

Usage fields read from a conversation file's `message.usage` (all optional):
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens,
    cache_creation.ephemeral_5m_input_tokens / ephemeral_1h_input_tokens (split of the writes; without
    it every write is priced as a 5-minute write, which is Claude Code's default),
    speed ("fast"), inference_geo ("us"), server_tool_use.web_search_requests
"""
import datetime
import json
import os
import re

PRICES_FILE = os.environ.get("CLAUDE_PRICES", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json"))
MODELS_DEV_FILE = os.environ.get("MODELS_DEV_FILE", "/state/models-dev.json")
# Providers whose models.dev price is used for a Claude model, in this order (the maker first)
DEV_PROVIDERS = ("anthropic", "amazon-bedrock", "google-vertex-anthropic", "openrouter")
_DATE = re.compile(r"-\d{8}$")
_table = {"mtime": None, "data": None}
_dev = {"mtime": None, "data": {}}


def table():
    mtime = os.path.getmtime(PRICES_FILE)
    if _table["mtime"] != mtime:
        with open(PRICES_FILE, encoding="utf-8") as f:
            _table.update(mtime=mtime, data=json.load(f))
    return _table["data"]


def normalise(model):
    """'claude-sonnet-4-5-20250929[1m]' -> 'claude-sonnet-4-5'."""
    m = (model or "").strip().lower()
    m = re.sub(r"\[.*?\]$", "", m)
    m = m.split("/")[-1].split("@")[0]          # bedrock/vertex style prefixes and @dates
    m = re.sub(r"^(us|eu|apac|global)\.anthropic\.", "", m)
    m = re.sub(r"-v\d+(:\d+)?$", "", m)          # bedrock "-v1:0"
    return _DATE.sub("", m)


def _dev_period(cost):
    """A prices.json-like period from a models.dev cost (USD per million). Missing cache prices follow
    Anthropic's multipliers: reads 0.1 × input, 5-minute writes 1.25 ×, 1-hour writes 2 ×."""
    inp = float(cost.get("input") or 0)
    p = {"from": "", "source": "models.dev", "input": inp, "output": float(cost.get("output") or 0),
         "cache_read": float(cost["cache_read"]) if cost.get("cache_read") is not None else inp * 0.1,
         "cache_write_5m": float(cost["cache_write"]) if cost.get("cache_write") is not None else inp * 1.25,
         "cache_write_1h": inp * 2}
    over = cost.get("context_over_200k")
    if isinstance(over, dict) and over.get("input"):
        oi = float(over["input"])
        p["tiers"] = [{"over": 200000, "input": oi, "output": float(over.get("output") or p["output"]),
                       "cache_read": float(over.get("cache_read") or oi * 0.1),
                       "cache_write_5m": float(over.get("cache_write") or oi * 1.25), "cache_write_1h": oi * 2}]
    return p


def dev_prices():
    """normalised model id -> period, from the models.dev copy; {} when there is none. Reloaded when it changes."""
    try:
        mtime = os.path.getmtime(MODELS_DEV_FILE)
    except OSError:
        return {}
    if _dev["mtime"] != mtime:
        data = {}
        try:
            with open(MODELS_DEV_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            order = {p: i for i, p in enumerate(DEV_PROVIDERS)}
            for prov in sorted((p for p in raw if p in order), key=order.get):
                for mid, mdata in ((raw[prov] or {}).get("models") or {}).items():
                    cost = (mdata or {}).get("cost")
                    if isinstance(cost, dict) and (cost.get("input") or 0) > 0:
                        data.setdefault(normalise(mid).replace(".", "-"), _dev_period(cost))
        except (OSError, ValueError, TypeError, AttributeError):
            data = {}
        _dev.update(mtime=mtime, data=data)
    return _dev["data"]


def period_for(model, ts_ms):
    """The price period of a model at a time: prices.json, else models.dev, else None."""
    models = table()["models"]
    name = normalise(model)
    keys = [k for k in models if name == k or name.startswith(k + "-")]
    if not keys:
        return dev_prices().get(name.replace(".", "-"))
    periods = models[max(keys, key=len)]
    day = datetime.datetime.fromtimestamp((ts_ms or 0) / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
    chosen = None
    for p in sorted(periods, key=lambda p: p["from"]):
        if p["from"] <= day:
            chosen = p
    return chosen or sorted(periods, key=lambda p: p["from"])[0]


def usage_extras(usage):
    """The parts of `usage` beyond the four token counts, in a compact dict (None when there is nothing)."""
    usage = usage or {}
    cc = usage.get("cache_creation") or {}
    out = {}
    if isinstance(cc, dict) and cc.get("ephemeral_1h_input_tokens"):
        out["w1h"] = int(cc.get("ephemeral_1h_input_tokens") or 0)
    if usage.get("speed") == "fast":
        out["fast"] = 1
    if str(usage.get("inference_geo") or "").lower() == "us":
        out["geo_us"] = 1
    ws = (usage.get("server_tool_use") or {}).get("web_search_requests")
    if ws:
        out["ws"] = int(ws)
    return out or None


def cost(model, ts_ms, inp, out, cache_read, cache_write, extras=None):
    """USD of one request, or None when the model has no price."""
    if model in (None, "", "<synthetic>", "unknown"):
        return None
    p = period_for(model, ts_ms)
    if p is None:
        return None
    extras = extras or {}
    w1h = min(extras.get("w1h", 0), cache_write)
    w5m = cache_write - w1h
    prompt = inp + cache_read + cache_write
    rates = dict(p)
    for tier in sorted(p.get("tiers", []), key=lambda t: t["over"]):
        if prompt > tier["over"]:
            rates.update(tier)
    base_in, base_out = rates["input"], rates["output"]
    factor = 1.0
    if extras.get("fast") and p.get("fast"):
        factor = p["fast"]["input"] / base_in   # caching multipliers apply on top of the fast price
        base_out = p["fast"]["output"]
    usd = (inp * base_in * factor + out * base_out + cache_read * rates["cache_read"] * factor
           + w5m * rates["cache_write_5m"] * factor + w1h * rates["cache_write_1h"] * factor) / 1_000_000
    if extras.get("geo_us") and p.get("geo_us"):
        usd *= p["geo_us"]
    usd += extras.get("ws", 0) * table().get("web_search_per_request", 0)
    return usd
