"""Claude Code's usage ledger (ADR 0002): the datasets the /data API serves.

Built from the conversation index (every session ever, with its project) and the telemetry the index
reads from Loki. The cost of each message is hybrid: the telemetry's when Claude Code reported it,
otherwise the estimate from prices.json, otherwise "missing" (see index.hybrid_cost).

usage        one row per assistant message (tool: "Claude Code") with tokens: ts, session, project, provider, model, agent
             ("principal" or "subagente"), subagent, skill (attributionSkill), effort and origin (from the
             telemetry, else from the conversation file; "desconocido" without either), cost, cost_source (telemetry | computed | missing),
             cost_telemetry, cost_computed, telemetry (1 when the telemetry reported it), missing,
             input, output, reasoning, cache_read, cache_write, tokens, messages
sessions     sessions with at least one message with tokens, dated by creation: ts, session, project, sessions
tools        finished tool calls: ts, session, project, tool, model, status, error_class, calls, errors,
             avoidable_errors (errors outside coach/errors.py NOT_AVOIDABLE), bytes (size of the result put
             in the context), measured (1 when the size is known), duration_ms and timed (1 when the
             duration is known; from toolUseResult.durationMs, else result time - call time, which
             includes waiting for a permission prompt)
prompts      one row per turn (a prompt and every model call answering it): ts, session, project,
             prompt_id, model (the one that cost most), prompt (its opening, only with PROMPT_TEXT=1),
             cost, tokens, messages
compactions  ts, session, project, trigger, compactions
interrupts   answers the user stopped: ts, session, project, interrupts
skills       skill and command uses: ts, kind (skill | command), skill, project, activations, ok,
             as_command, as_skill
commands     the cost of the turns each command launched, per message: ts (the command's), command,
             project, model, origin, cost, cost_source, messages
"""
import index
from common import ledger
from coach.errors import NOT_AVOIDABLE

NO_TELEMETRY = "desconocido"
# What the «Texto» column says if the collector runs with PROMPT_TEXT=0
PROMPT_TEXT_OFF = "(el colector no lee el texto: PROMPT_TEXT=0)"


def _sessions():
    ix = index.INDEX
    with ix.lock:
        sessions = [dict(s, msgs=list(s["msgs"].values()), calls=list(s["calls"].values()),
                         compactions=list(s["compactions"]), interrupts=list(s["interrupts"]),
                         commands=list(s["commands"]), skills=list(s["skills"]),
                         command_prompts=dict(s["command_prompts"]))
                    for s in ix.sessions.values()]
        costs = dict(ix.costs)
        requests = dict(ix.requests)
        meta = dict(ix.request_meta)
    return sessions, costs, requests, meta


def _has_tokens(m):
    return m[2] + m[3] + m[4] + m[5] > 0 and m[1] != "<synthetic>"


def _origin(m, requests):
    req = requests.get(m[7]) if m[7] else None
    return req[2] if req else ("subagente" if m[6] else "principal")


def usage():
    sessions, costs, requests, meta = _sessions()
    rows = []
    for s in sessions:
        for m in s["msgs"]:
            if not _has_tokens(m):
                continue
            cost = index.hybrid_cost(costs, m)
            source = index.cost_source(costs, m)
            tel = costs.get(m[7]) if m[7] else None
            computed = m[10] if len(m) > 10 else None
            effort = (meta.get(m[7]) or ("", "", 0))[1] if m[7] in meta else ""
            effort = effort or (m[11] if len(m) > 11 else None) or ""  # the conversation file has it too
            rows.append({"tool": "Claude Code", "ts": m[0], "session": s["id"], "project": s["project"], "provider": "anthropic", "model": m[1],
                         "agent": "subagente" if m[6] else "principal", "subagent": "sí" if m[6] else "no",
                         "skill": m[8] or "", "effort": effort or NO_TELEMETRY, "origin": _origin(m, requests),
                         "model_effort": "%s · %s" % (m[1], effort or NO_TELEMETRY),
                         "cost": cost or 0.0, "cost_source": source,
                         "cost_telemetry": tel or 0.0, "cost_computed": computed or 0.0,
                         "telemetry": 1 if tel is not None else 0, "missing": 1 if cost is None else 0,
                         "input": m[2], "output": m[3], "reasoning": 0, "cache_read": m[4], "cache_write": m[5],
                         "tokens": m[2] + m[3] + m[4] + m[5], "messages": 1})
    return rows


def sessions():
    rows = []
    for s in _sessions()[0]:
        if s["created"] and any(_has_tokens(m) for m in s["msgs"]):
            rows.append({"ts": s["created"], "session": s["id"], "project": s["project"], "sessions": 1})
    return rows


def tools():
    rows = []
    for s in _sessions()[0]:
        for c in s["calls"]:  # [ts, tool, model, turn, arg hash, status, error class, sidechain]
            if not c[0] or not c[5]:
                continue
            err = c[5] == "error"
            rows.append({"ts": c[0], "session": s["id"], "project": s["project"], "tool": c[1], "model": c[2],
                         "status": "error" if err else "ok", "error_class": (c[6] or "other") if err else "",
                         "calls": 1, "errors": 1 if err else 0,
                         "avoidable_errors": 1 if err and (c[6] or "other") not in NOT_AVOIDABLE else 0,
                         "bytes": (c[8] or 0) if len(c) > 9 else 0, "measured": 1 if len(c) > 9 and c[8] is not None else 0,
                         "duration_ms": (c[9] or 0) if len(c) > 9 else 0, "timed": 1 if len(c) > 9 and c[9] is not None else 0})
    return rows


def prompts():
    """Cost of each turn: the prompt and every model call that answered it (main thread and subagents)."""
    sessions, costs, _requests, _meta = _sessions()
    rows = []
    for s in sessions:
        texts = s.get("prompts") or {}
        turns = {}
        for m in s["msgs"]:
            turn = m[9] if len(m) > 9 else None
            if not turn or not _has_tokens(m):
                continue
            t = turns.setdefault(turn, {"ts": m[0], "cost": 0.0, "tokens": 0, "messages": 0, "by_model": {}})
            cost = index.hybrid_cost(costs, m) or 0.0
            t["ts"] = min(t["ts"], m[0]) if t["ts"] else m[0]
            t["cost"] += cost
            t["tokens"] += m[2] + m[3] + m[4] + m[5]
            t["messages"] += 1
            t["by_model"][m[1]] = t["by_model"].get(m[1], 0) + cost
        for turn, t in turns.items():
            rows.append({"ts": (s.get("turns") or {}).get(turn) or t["ts"], "session": s["id"], "project": s["project"],
                         "prompt_id": turn, "model": max(t["by_model"], key=t["by_model"].get),
                         "prompt": texts.get(turn, "") if index.PROMPT_TEXT else PROMPT_TEXT_OFF,
                         "cost": t["cost"], "tokens": t["tokens"], "messages": t["messages"]})
    return rows


def compactions():
    return [{"ts": ts, "session": s["id"], "project": s["project"], "trigger": trigger or "", "compactions": 1}
            for s in _sessions()[0] for ts, _pre, _post, trigger in s["compactions"] if ts]


def interrupts():
    return [{"ts": ts, "session": s["id"], "project": s["project"], "interrupts": 1}
            for s in _sessions()[0] for ts, _turn in s["interrupts"] if ts]


def skills():
    rows = []
    for s in _sessions()[0]:
        for kind, uses in (("command", s["commands"]), ("skill", s["skills"])):
            for ts, name in uses:
                rows.append({"ts": ts, "kind": kind, "skill": name, "project": s["project"], "activations": 1, "ok": 1,
                             "as_command": 1 if kind == "command" else 0, "as_skill": 1 if kind == "skill" else 0})
    return rows


def commands():
    """Every message of the turns a command launched (they share its prompt id), with its hybrid cost."""
    sessions, costs, requests, _meta = _sessions()
    rows = []
    for s in sessions:
        launched = s["command_prompts"]  # prompt id -> (ts, command)
        if not launched:
            continue
        for m in s["msgs"]:
            hit = launched.get(m[9]) if len(m) > 9 else None
            if not hit or not _has_tokens(m):
                continue
            cost = index.hybrid_cost(costs, m)
            rows.append({"ts": hit[0], "command": hit[1], "project": s["project"], "model": m[1],
                         "origin": _origin(m, requests), "cost": cost or 0.0,
                         "cost_source": index.cost_source(costs, m), "messages": 1})
    return rows


LEDGER = ledger.Ledger()
for _name, _build in (("usage", usage), ("sessions", sessions), ("tools", tools), ("prompts", prompts), ("compactions", compactions),
                      ("interrupts", interrupts), ("skills", skills), ("commands", commands)):
    LEDGER.register(_name, _build)
