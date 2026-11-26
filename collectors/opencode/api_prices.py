"""API price of OpenCode's models, to value the messages OpenCode stored with cost 0.

OpenCode stores the cost of each answer with the prices of its models.dev catalog (`catalog`: models.json
in OpenCode 1.x, its database in 2.x). With a
subscription (GitHub Copilot, a company provider…) or a model that cache does not know, it stores 0.
To show what those messages would cost at API prices, as the Claude Code dashboard does, a message
with cost 0 is valued with tokens × price (cost_source "computed"); one that has a cost keeps it ("tool").

The price of a model: its own provider's in models.json when above 0; otherwise the reference price of
the same model at its maker (anthropic, openai, google…), matched by name with dots, hyphens and case
ignored ("claude-opus-4.6" = "claude-opus-4-6"). Local providers (LM Studio, Ollama…) are free.
"""
import re

import catalog

LOCAL_PROVIDERS = {"lmstudio", "ollama", "llama.cpp", "llamacpp", "llama-cpp", "vllm", "localai", "jan"}
# Where a model's reference price is looked up first: the makers, then everyone else in models.json
REFERENCE = ("anthropic", "openai", "google", "xai", "zai", "zhipuai", "deepseek", "mistral", "moonshotai",
             "alibaba", "minimax", "meta", "amazon-bedrock", "azure", "openrouter")
FIELDS = ("input", "output", "cache_read", "cache_write")
_cache = {"stamp": None, "own": {}, "ref": {}}


def key(model):
    """'anthropic/Claude-Opus-4.6-20260101' -> 'claude-opus-4-6'."""
    m = (model or "").lower().split("/")[-1]
    m = re.sub(r"[._:]", "-", m)
    return re.sub(r"-\d{8}$", "", m)


def _paid(cost):
    return isinstance(cost, dict) and any((cost.get(k) or 0) > 0 for k in ("input", "output"))


def _load():
    raw = catalog.load()
    if _cache["stamp"] != catalog.stamp():
        own, ref = {}, {}
        order = {p: i for i, p in enumerate(REFERENCE)}
        for prov in sorted(raw, key=lambda p: (order.get(p, len(order)), p)):
            for mid, mdata in ((raw[prov] or {}).get("models") or {}).items():
                cost = mdata.get("cost")
                if isinstance(cost, dict):
                    own[(prov, key(mid))] = cost
                    if _paid(cost):
                        ref.setdefault(key(mid), (prov, cost))
        _cache.update(stamp=catalog.stamp(), own=own, ref=ref)
    return _cache


def price(provider, model):
    """(price per million tokens, where it comes from) or (None, None). The source is "" for the
    provider's own price, the maker's name for a reference price, or "local"."""
    if (provider or "").lower() in LOCAL_PROVIDERS:
        return {k: 0 for k in FIELDS}, "local"
    data = _load()
    own = data["own"].get((provider, key(model)))
    if _paid(own):
        return own, ""
    ref = data["ref"].get(key(model))
    if ref:
        return ref[1], ref[0]
    return (own, "") if own is not None else (None, None)


def cost(provider, model, inp, out, reasoning, cache_read, cache_write):
    """USD at API price of one message's tokens, or None when no price is known."""
    p, _src = price(provider, model)
    if p is None:
        return None
    return ((inp or 0) * (p.get("input") or 0) + ((out or 0) + (reasoning or 0)) * (p.get("output") or 0)
            + (cache_read or 0) * (p.get("cache_read") or 0)
            + (cache_write or 0) * (p.get("cache_write") or p.get("input") or 0)) / 1e6


def hybrid(m):
    """(cost, source) of a message: what OpenCode stored ("tool"), else the API price ("computed"), else
    (0, "missing") for a message with tokens and no known price. Messages without tokens cost 0 ("tool")."""
    if m.cost:
        return m.cost, "tool"
    tokens = (m.inp or 0) + (m.out or 0) + (m.reasoning or 0) + (m.cache_read or 0) + (m.cache_write or 0)
    if not tokens:
        return 0.0, "tool"
    c = cost(m.provider, m.model, m.inp, m.out, m.reasoning, m.cache_read, m.cache_write)
    return (c, "computed") if c is not None else (0.0, "missing")
