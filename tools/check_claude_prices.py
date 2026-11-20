"""Check the price table against your real Claude Code conversations (ADR 0002).

    python tools/check_claude_prices.py                 # reads ~/.claude/projects
    python tools/check_claude_prices.py <projects dir>

Read-only. Prints, per model: messages, tokens, whether prices.json has a price for it, how many
messages used 1-hour cache writes, fast mode, US-only inference or web search, and the estimated cost.
Never prints conversation text, titles or paths. A model listed as SIN PRECIO needs an entry in
collectors/claude/prices.json, or its messages count as "missing" in the dashboard.

With --fields it also lists which fields the conversation files and ~/.claude/stats-cache.json have
(names, how often and their type; never values), to see whether the effort of each request or the
cost of the calls that are not in the conversations could be read without the telemetry.

To compare the estimate with the telemetry: http://localhost:9100/data/usage?group=model&f.cost_source=telemetry&measures=cost_telemetry,cost_computed
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors", "claude"))
sys.dont_write_bytecode = True
import pricing  # noqa: E402


def ts_ms(text):
    import datetime
    try:
        return int(datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, AttributeError):
        return 0


INTERESTING = ("effort", "thinking", "budget", "speed", "duration", "reasoning", "cost", "usd", "tier", "geo")


_ID = re.compile(r"^(toolu_|msg_|req_|srvtoolu_)[A-Za-z0-9]+$|^[0-9a-f]{8}-[0-9a-f-]{27}$|^\d+$")
# Fields that hold the tool inputs or file contents: only their presence is shown, never what is inside
_OPAQUE = ("wireToolInputs", "toolUseResult.structuredPatch", "toolUseResult.file", "mcpMeta", "serverClassifierContext",
           "origin", "permissionDecision.reasonCode")


def _walk(obj, prefix, out, depth=0):
    """Count key paths (lists collapsed to [], ids collapsed to <id>) and the JSON type found at each one."""
    if depth > 5 or any(prefix.endswith(o) for o in _OPAQUE):
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            k = "<id>" if _ID.match(str(k)) else k
            path = prefix + "." + k if prefix else k
            out.setdefault(path, {})
            t = type(v).__name__
            out[path][t] = out[path].get(t, 0) + 1
            _walk(v, path, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:50]:
            _walk(v, prefix + "[]", out, depth + 1)


def fields(root):
    """Field names of the conversation lines that matter here, and the shape of stats-cache.json."""
    paths = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    kind = j.get("type", "?")
                    if kind == "assistant":
                        m = j.get("message") or {}
                        _walk({k: v for k, v in j.items() if k != "message"}, "assistant", paths)
                        _walk({k: v for k, v in m.items() if k != "content"}, "assistant.message", paths)
                    elif kind == "user":
                        _walk({k: v for k, v in j.items() if k not in ("message", "toolUseResult")}, "user", paths)
                        if isinstance(j.get("toolUseResult"), dict):
                            _walk({k: (v if isinstance(v, (int, float, bool)) else type(v).__name__)
                                   for k, v in j["toolUseResult"].items()}, "user.toolUseResult", paths)
                    else:
                        _walk({"type": kind}, "line", paths)
    out = sys.stdout
    print("Campos de las conversaciones (ruta: tipos y veces). Marcados con * los que pueden servir para effort o coste:\n")
    for path in sorted(paths):
        if path.startswith("assistant.message.content") or ".content" in path:
            continue
        mark = "*" if any(w in path.lower() for w in INTERESTING) else " "
        print(" %s %-70s %s" % (mark, path[:70], ", ".join("%s×%d" % kv for kv in sorted(paths[path].items()))))
    stats = os.path.join(os.path.dirname(root.rstrip("/\\")), "stats-cache.json")
    print("\nstats-cache.json (%s):" % ("no existe" if not os.path.exists(stats) else "estructura, sin valores"))
    if os.path.exists(stats):
        shape = {}
        with open(stats, encoding="utf-8") as f:
            _walk(json.load(f), "", shape)
        for path in sorted(shape)[:200]:
            print("   %-70s %s" % (path[:70], ", ".join("%s×%d" % kv for kv in sorted(shape[path].items()))))


# Fields whose values are a closed set of words (never text written by you or by Claude): safe to count
ENUMS = {
    "assistant": ("effort", "perTurnEffort"),
    "assistant.message.usage": ("speed", "service_tier", "inference_geo"),
    "user.permissionDecision": ("decision", "source", "reasonType", "ruleSource"),
    "user": ("toolDenialKind", "permissionMode"),
}


def values(root):
    """How often each value of ENUMS appears, to map them to what the telemetry calls them."""
    from collections import Counter
    counts = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    for base, keys in ENUMS.items():
                        node = j
                        parts = base.split(".")
                        if parts[0] != j.get("type"):
                            continue
                        for p in parts[1:]:
                            node = node.get(p) if isinstance(node, dict) else None
                        if not isinstance(node, dict):
                            continue
                        for k in keys:
                            v = node.get(k)
                            if v is not None and not isinstance(v, (dict, list)):
                                counts.setdefault(base + "." + k, Counter())[str(v)[:40]] += 1
    for field in sorted(counts):
        print("%s:" % field)
        for v, n in counts[field].most_common(15):
            print("    %-40s %d" % (v, n))


def main(root):
    stats = defaultdict(lambda: defaultdict(float))
    seen = set()
    files = 0
    for folder, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            files += 1
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"type":"assistant"' not in line and '"type": "assistant"' not in line:
                        continue
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    m = j.get("message") or {}
                    u = m.get("usage") or {}
                    mid = m.get("id") or j.get("uuid")
                    if mid in seen or not u:
                        continue
                    seen.add(mid)
                    model = m.get("model") or "unknown"
                    if model == "<synthetic>":
                        continue
                    inp, out = u.get("input_tokens") or 0, u.get("output_tokens") or 0
                    cr, cw = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
                    ex = pricing.usage_extras(u) or {}
                    cost = pricing.cost(model, ts_ms(j.get("timestamp")), inp, out, cr, cw, ex)
                    s = stats[pricing.normalise(model)]
                    s["messages"] += 1
                    s["tokens"] += inp + out + cr + cw
                    s["priced"] += cost is not None
                    s["cost"] += cost or 0
                    s["has_split"] += "cache_creation" in u
                    s["w1h"] += bool(ex.get("w1h"))
                    s["fast"] += bool(ex.get("fast"))
                    s["geo_us"] += bool(ex.get("geo_us"))
                    s["web_search"] += ex.get("ws", 0)
    print("%d ficheros, %d mensajes con uso\n" % (files, len(seen)))
    head = ("Modelo", "Mensajes", "Tokens (M)", "Precio", "Coste est.", "Con desglose caché", "Escrit. 1 h", "Rápido", "EE. UU.", "Búsquedas")
    print("%-28s %9s %11s %10s %11s %19s %11s %7s %8s %10s" % head)
    total = 0
    for model, s in sorted(stats.items(), key=lambda x: -x[1]["cost"]):
        priced = "sí" if s["priced"] == s["messages"] else ("SIN PRECIO" if not s["priced"] else "parcial")
        total += s["cost"]
        print("%-28s %9d %11.2f %10s %11.2f %19d %11d %7d %8d %10d" % (
            model[:28], s["messages"], s["tokens"] / 1e6, priced, s["cost"], s["has_split"], s["w1h"], s["fast"], s["geo_us"], s["web_search"]))
    print("\nCoste estimado total: %.2f USD" % total)
    missing = [m for m, s in stats.items() if not s["priced"]]
    if missing:
        print("Modelos sin precio en prices.json: %s" % ", ".join(sorted(missing)))
    if not any(s["has_split"] for s in stats.values()):
        print("Aviso: ningún mensaje trae el desglose de escrituras de caché (5 min / 1 h); se cobran todas como 5 min.")
    return 1 if missing else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("--fields", "--values")]
    root = args[0] if args else os.path.join(os.path.expanduser("~"), ".claude", "projects")
    if "--fields" in sys.argv:
        fields(root)
        sys.exit(0)
    if "--values" in sys.argv:
        values(root)
        sys.exit(0)
    sys.exit(main(root))
