"""Estimated cost of one Claude API request from its token usage (ADR 0002).

Used only when Claude Code's telemetry did not report the request's cost (the stack was down, the
telemetry was off, or the request is older than the telemetry). The table is prices.json; see its
_doc for the rules. A model that is not in the table gives None ("missing"), never 0.

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
_DATE = re.compile(r"-\d{8}$")
_table = {"mtime": None, "data": None}


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


def period_for(model, ts_ms):
    """The price period of a model at a time, or None if the model is not in the table."""
    models = table()["models"]
    name = normalise(model)
    keys = [k for k in models if name == k or name.startswith(k + "-")]
    if not keys:
        return None
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
