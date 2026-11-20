"""OpenCode's usage ledger (ADR 0002): the datasets the /data API serves.

Built from what the exporter already keeps in memory, so it reads nothing extra from opencode.db:
the coach's snapshot (messages, sessions, tool calls, compactions, refreshed in the background) and
the skill and command scan. Columns follow the shared ledger contract:

usage        one row per assistant message (tool: "OpenCode"): ts, session, project, provider, model, agent, subagent,
             cost, cost_source ("tool": the cost OpenCode stored; "computed": OpenCode stored 0 (subscription or
             unknown model) and it is tokens × API price, see api_prices; "missing": 0 with no known price),
             cost_tool (what OpenCode stored), cost_computed, missing, input, output, reasoning,
             cache_read, cache_write, tokens, messages, aborted
sessions     one row per main session (no parent), dated by its creation: ts, session, project, sessions
tools        one row per finished tool call: ts, session, project, tool, model, agent, status,
             error_class, calls, errors, avoidable_errors (errors not in ledger.UNAVOIDABLE_ERRORS)
prompts      one row per turn (a user message and every assistant message answering it): ts, session,
             project, subagent, prompt_id, model (the one that cost most), agent, prompt (its opening; the
             dashboard asks for asterisks with mask=prompt), cost, tokens, messages
compactions  ts, session, project, compactions
skills       skill and command activations and the cost of the turns they ran in: ts, kind, skill,
             project, provider, model, agent, result, activations, ok, failed, cost. An activation
             row carries activations=1 and ok or failed=1; the cost of its turn comes in separate rows (activations=0), one per model
             that answered, split equally when one turn loaded several skills.
"""
import sys

import api_prices
from common import ledger
from coach import metrics as coach_metrics


def _exporter():
    return sys.modules.get("exporter") or sys.modules["__main__"]


def _snapshot():
    loaded, _at = coach_metrics.snapshot()
    if loaded is None:  # before the background thread's first reading
        return [], {}, [], []
    return loaded


def usage():
    msgs, sessions, _calls, _comp = _snapshot()
    rows = []
    for m in msgs:
        if m.role != "assistant":
            continue
        cost, source = api_prices.hybrid(m)
        s = sessions.get(m.session) or {}
        rows.append({"tool": "OpenCode", "ts": m.time, "session": m.session, "project": s.get("project", "global"),
                     "provider": m.provider, "model": m.model, "agent": m.agent,
                     "subagent": "sí" if s.get("parent") else "no", "cost_source": source,
                     "cost": cost, "cost_tool": m.cost or 0.0, "cost_computed": cost if source == "computed" else 0.0,
                     "missing": 1 if source == "missing" else 0, "input": m.inp, "output": m.out, "reasoning": m.reasoning,
                     "cache_read": m.cache_read, "cache_write": m.cache_write, "tokens": m.tokens,
                     "messages": 1, "aborted": 1 if m.error == "MessageAbortedError" else 0})
    return rows


def sessions():
    _msgs, sess, _calls, _comp = _snapshot()
    return [{"ts": s["created"], "session": sid, "project": s["project"], "sessions": 1}
            for sid, s in sess.items() if not s["parent"]]


def tools():
    msgs, sess, calls, _comp = _snapshot()
    by_id = {m.id: m for m in msgs}
    rows = []
    for c in calls:
        if c.status in ("pending", "running"):
            continue
        m = by_id.get(c.message)
        rows.append({"ts": c.time, "session": c.session, "project": (sess.get(c.session) or {}).get("project", "global"),
                     "tool": c.tool, "model": m.model if m else "unknown", "agent": m.agent if m else "unknown",
                     "status": "error" if c.status == "error" else "ok", "error_class": c.error_class or "",
                     "calls": 1, "errors": 1 if c.status == "error" else 0,
                     "avoidable_errors": 1 if c.status == "error" and c.error_class not in ledger.UNAVOIDABLE_ERRORS else 0})
    return rows


PROMPT_TEXT_OFF = "(el colector no lee el texto: PROMPT_TEXT=0)"


def prompts():
    ex = _exporter()
    msgs, sess, _calls, _comp = _snapshot()
    by_id = {m.id: m for m in msgs}
    with ex._skills_lock:
        texts = dict(ex._skills.get("prompts", {}))
    turns = {}
    for m in msgs:
        if m.role != "assistant" or not m.parent:
            continue
        t = turns.setdefault(m.parent, {"cost": 0.0, "tokens": 0, "messages": 0, "by_model": {}, "session": m.session, "first": m.time})
        cost = api_prices.hybrid(m)[0]
        t["cost"] += cost
        t["tokens"] += m.tokens
        t["messages"] += 1
        t["first"] = min(t["first"], m.time)
        key = (m.model, m.agent)
        t["by_model"][key] = t["by_model"].get(key, 0) + cost
    rows = []
    for parent, t in turns.items():
        user = by_id.get(parent)
        s = sess.get(t["session"]) or {}
        model, agent = max(t["by_model"], key=t["by_model"].get)
        rows.append({"ts": user.time if user else t["first"], "session": t["session"], "project": s.get("project", "global"),
                     "subagent": "sí" if s.get("parent") else "no", "prompt_id": parent, "model": model, "agent": agent,
                     "prompt": texts.get(parent, "") if ex.PROMPT_TEXT else PROMPT_TEXT_OFF,
                     "cost": t["cost"], "tokens": t["tokens"], "messages": t["messages"]})
    return rows


def compactions():
    _msgs, sess, _calls, comp = _snapshot()
    return [{"ts": t, "session": s, "project": (sess.get(s) or {}).get("project", "global"), "compactions": 1}
            for s, _mid, t in comp]


def skills():
    """Same attribution as exporter.skill_usage, as rows with a timestamp instead of a UTC day."""
    ex = _exporter()
    msgs, _sess, _calls, _comp = _snapshot()
    turns = {}  # user message -> {(provider, model, agent): cost}
    for m in msgs:
        if m.role == "assistant" and m.parent:
            parts = turns.setdefault(m.parent, {})
            key = (m.provider, m.model, m.agent)
            parts[key] = parts.get(key, 0) + api_prices.hybrid(m)[0]
    with ex._skills_lock:
        calls = list(ex._skills["calls"].values())
        commands = list(ex._skills["commands"].items())
    rows, by_turn = [], {}
    for _day, name, status, parent, wt, prov, model, agent, ts in calls:
        if status in ("pending", "running"):
            continue
        proj = ex.project_name(wt)
        result = "ok" if status == "completed" else "error"
        rows.append({"ts": ts, "kind": "skill", "skill": name, "project": proj, "provider": prov, "model": model,
                     "agent": agent, "result": result, "activations": 1,
                     "ok": 1 if result == "ok" else 0, "failed": 0 if result == "ok" else 1, "cost": 0.0})
        if result == "ok" and parent:
            by_turn.setdefault(parent, (ts, proj, set()))[2].add(name)
    for parent, (ts, proj, names) in by_turn.items():
        for name in names:
            for (prov, model, agent), part in turns.get(parent, {}).items():
                rows.append({"ts": ts, "kind": "skill", "skill": name, "project": proj, "provider": prov, "model": model,
                             "agent": agent, "result": "ok", "activations": 0, "ok": 0, "failed": 0,
                             "cost": part / len(names)})
    for message_id, (_day, name, wt, ts) in commands:
        proj = ex.project_name(wt)
        parts = turns.get(message_id, {})
        main = max(parts, key=parts.get) if parts else ("unknown", "unknown", "unknown")
        rows.append({"ts": ts, "kind": "command", "skill": name, "project": proj, "provider": main[0], "model": main[1],
                     "agent": main[2], "result": "ok", "activations": 1, "ok": 1, "failed": 0, "cost": 0.0})
        for (prov, model, agent), part in parts.items():
            rows.append({"ts": ts, "kind": "command", "skill": name, "project": proj, "provider": prov, "model": model,
                         "agent": agent, "result": "ok", "activations": 0, "ok": 0, "failed": 0, "cost": part})
    return rows


LEDGER = ledger.Ledger()
for _name, _build in (("usage", usage), ("sessions", sessions), ("tools", tools), ("prompts", prompts),
                      ("compactions", compactions), ("skills", skills)):
    LEDGER.register(_name, _build)
