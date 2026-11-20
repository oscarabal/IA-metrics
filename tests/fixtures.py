"""Deterministic sample data for both tools, written to a temporary folder.

The data covers the cases the collectors treat specially: subagents, tool errors, skills, custom
commands, compactions, an interrupted answer, two projects and activity close to midnight (so a
local time zone and UTC put it on different days). Every figure the tests check is derived from the
constants below, never typed twice.
"""
import json
import os
import sqlite3

# 2026-11-18 .. 2026-11-20, all UTC. 23:30 UTC on the 18th is 00:30 on the 19th in Europe/Madrid.
T0 = 1794960000000                 # 2026-11-18T00:00:00Z in ms
H = 3600 * 1000
D = 24 * H

# ------------------------------------------------------------------ OpenCode
OC_PROJECTS = {"prj_a": "C:/Workspace/demo", "prj_b": "C:/Workspace/api"}
# session id, project, parent, title, created
OC_SESSIONS = [
    ("ses_aaa001", "prj_a", None, "Arreglar login", T0 + 10 * H),
    ("ses_aaa002", "prj_a", "ses_aaa001", "Subagente explorador", T0 + 10 * H + 60000),
    ("ses_bbb001", "prj_b", None, "API de pagos", T0 + D + 9 * H),
    ("ses_bbb002", "prj_b", None, "Sesión de noche", T0 + 23 * H + 30 * 60000),
]
# message id, session, time, role, parent(user msg), agent, provider, model, cost, (in, out, reasoning, cache_read, cache_write), error
OC_MESSAGES = [
    ("msg_0001", "ses_aaa001", T0 + 10 * H + 1000, "user", None, "build", None, None, 0, None, None),
    ("msg_0002", "ses_aaa001", T0 + 10 * H + 5000, "assistant", "msg_0001", "build", "anthropic", "claude-sonnet-4-5", 0.10, (1000, 200, 0, 5000, 300), None),
    ("msg_0003", "ses_aaa001", T0 + 10 * H + 9000, "assistant", "msg_0001", "build", "anthropic", "claude-sonnet-4-5", 0.05, (500, 100, 0, 6000, 0), None),
    ("msg_0004", "ses_aaa002", T0 + 10 * H + 70000, "user", None, "explore", None, None, 0, None, None),
    ("msg_0005", "ses_aaa002", T0 + 10 * H + 80000, "assistant", "msg_0004", "explore", "openai", "gpt-5-mini", 0.01, (2000, 50, 30, 0, 0), None),
    ("msg_0006", "ses_bbb001", T0 + D + 9 * H + 1000, "user", None, "plan", None, None, 0, None, None),
    ("msg_0007", "ses_bbb001", T0 + D + 9 * H + 4000, "assistant", "msg_0006", "plan", "anthropic", "claude-opus-4-1", 0.80, (3000, 900, 0, 10000, 2000), None),
    ("msg_0008", "ses_bbb001", T0 + D + 9 * H + 9000, "assistant", "msg_0006", "plan", "anthropic", "claude-opus-4-1", 0.00, (0, 0, 0, 0, 0), "MessageAbortedError"),
    ("msg_0009", "ses_bbb002", T0 + 23 * H + 31 * 60000, "user", None, "build", None, None, 0, None, None),
    ("msg_0010", "ses_bbb002", T0 + 23 * H + 32 * 60000, "assistant", "msg_0009", "build", "anthropic", "claude-sonnet-4-5", 0.20, (800, 400, 0, 1000, 100), None),
    ("msg_0011", "ses_aaa001", T0 + 2 * D + 8 * H, "user", None, "build", None, None, 0, None, None),
    ("msg_0012", "ses_aaa001", T0 + 2 * D + 8 * H + 7000, "assistant", "msg_0011", "build", "anthropic", "claude-sonnet-4-5", 0.30, (1500, 600, 0, 9000, 500), None),
]
COMMAND_TEMPLATE = "Revisa el código del módulo indicado y propón mejoras concretas: $ARGUMENTS"
# part id, message, session, time, data
OC_PARTS = [
    ("prt_0001", "msg_0001", "ses_aaa001", T0 + 10 * H + 1000, {"type": "text", "text": "arregla el login"}),
    ("prt_0002", "msg_0002", "ses_aaa001", T0 + 10 * H + 5000, {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "a.py"}}}),
    ("prt_0003", "msg_0002", "ses_aaa001", T0 + 10 * H + 6000, {"type": "tool", "tool": "edit", "state": {"status": "error", "input": {"filePath": "a.py"}, "error": "oldString not found in content"}}),
    ("prt_0004", "msg_0003", "ses_aaa001", T0 + 10 * H + 9000, {"type": "tool", "tool": "skill", "state": {"status": "completed", "input": {"name": "pdf"}}}),
    ("prt_0005", "msg_0005", "ses_aaa002", T0 + 10 * H + 80000, {"type": "tool", "tool": "grep", "state": {"status": "completed", "input": {"pattern": "x"}}}),
    ("prt_0006", "msg_0006", "ses_bbb001", T0 + D + 9 * H + 1000, {"type": "text", "text": "Revisa el código del módulo indicado y propón mejoras concretas: pagos.py"}),
    ("prt_0007", "msg_0007", "ses_bbb001", T0 + D + 9 * H + 5000, {"type": "compaction"}),
    ("prt_0008", "msg_0010", "ses_bbb002", T0 + 23 * H + 32 * 60000, {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "ls"}}}),
    ("prt_0009", "msg_0012", "ses_aaa001", T0 + 2 * D + 8 * H + 7000, {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "b.py"}}}),
    # text OpenCode adds by itself (synthetic) is not the prompt; the user's text after it is
    ("prt_0010", "msg_0011", "ses_aaa001", T0 + 2 * D + 8 * H, {"type": "text", "synthetic": True, "text": "Called the Read tool"}),
    ("prt_0011", "msg_0011", "ses_aaa001", T0 + 2 * D + 8 * H, {"type": "text", "text": "revisa   los tests"}),
]


def make_opencode(root):
    """opencode.db, models.json and a commands folder under `root`; returns the paths."""
    data, cache, cmds = (os.path.join(root, d) for d in ("data", "cache", "commands"))
    for d in (data, cache, cmds):
        os.makedirs(d, exist_ok=True)
    db = os.path.join(data, "opencode.db")
    if os.path.exists(db):
        os.remove(db)
    c = sqlite3.connect(db)
    c.executescript("""
        create table project(id text primary key, worktree text, time_created int, time_updated int);
        create table session(id text primary key, project_id text, parent_id text, title text, directory text,
                             agent text, md text, model text, summary_additions int, summary_deletions int,
                             summary_files int, time_created int, time_updated int);
        create table message(id text primary key, session_id text, time_created int, time_updated int, data text);
        create table part(id text primary key, message_id text, session_id text, time_created int, time_updated int, data text);
    """)
    for pid, wt in OC_PROJECTS.items():
        c.execute("insert into project values(?,?,?,?)", (pid, wt, T0, T0))
    for sid, prj, parent, title, created in OC_SESSIONS:
        c.execute("insert into session(id,project_id,parent_id,title,time_created,time_updated) values(?,?,?,?,?,?)",
                  (sid, prj, parent, title, created, created + H))
    for mid, sid, t, role, parent, agent, prov, model, cost, tok, err in OC_MESSAGES:
        d = {"role": role, "agent": agent}
        if role == "assistant":
            i, o, r, cr, cw = tok
            d.update(parentID=parent, providerID=prov, modelID=model, cost=cost,
                     tokens={"input": i, "output": o, "reasoning": r, "cache": {"read": cr, "write": cw}},
                     time={"created": t, "completed": t + 1000})
            if err:
                d["error"] = {"name": err}
        c.execute("insert into message values(?,?,?,?,?)", (mid, sid, t, t, json.dumps(d)))
    for pid, mid, sid, t, d in OC_PARTS:
        c.execute("insert into part values(?,?,?,?,?,?)", (pid, mid, sid, t, t, json.dumps(d)))
    c.commit()
    c.close()
    with open(os.path.join(cache, "models.json"), "w", encoding="utf-8") as f:
        json.dump({"anthropic": {"models": {
                       "claude-sonnet-4-5": {"limit": {"context": 200000}, "cost": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write": 3.75}},
                       "claude-opus-4-1": {"limit": {"context": 200000}, "cost": {"input": 15, "output": 75, "cache_read": 1.5, "cache_write": 18.75}}}},
                   "openai": {"models": {"gpt-5-mini": {"limit": {"context": 400000}, "cost": {"input": 0.25, "output": 2, "cache_read": 0.025}}}},
                   "opencode": {"models": {"big-pickle": {"limit": {"context": 200000}, "cost": {"input": 0, "output": 0}}}}}, f)
    with open(os.path.join(cmds, "revisa.md"), "w", encoding="utf-8") as f:
        f.write("---\ndescription: revisión\n---\n" + COMMAND_TEMPLATE + "\n")
    return {"db": db, "models": os.path.join(cache, "models.json"), "commands": cmds, "quota": os.path.join(cache, "q")}


def oc_expected():
    """Totals of the assistant messages, the way the dashboard counts them."""
    a = [m for m in OC_MESSAGES if m[3] == "assistant"]
    tok = lambda m: sum(m[9])
    return {"cost": round(sum(m[8] for m in a), 6), "messages": len(a), "tokens": sum(tok(m) for m in a),
            "main_sessions": sum(1 for s in OC_SESSIONS if s[2] is None)}


# ------------------------------------------------------------------ Claude Code
CC_SESSIONS = {
    # session id: (project folder, cwd)
    "0f8fad5b-d9cb-469f-a165-70867728950e": ("C--Workspace-demo", "C:\\Workspace\\demo"),
    "7c9e6679-7425-40de-944b-e07fc1f90ae7": ("C--Workspace-api", "C:\\Workspace\\api"),
}
# session, ts, request id, model, (input, output, cache_read, cache_creation), sidechain
CC_ASSISTANT = [
    ("0f8fad5b-d9cb-469f-a165-70867728950e", T0 + 10 * H + 5000, "req_001", "claude-sonnet-4-5", (100, 200, 5000, 300), False),
    ("0f8fad5b-d9cb-469f-a165-70867728950e", T0 + 10 * H + 9000, "req_002", "claude-sonnet-4-5", (50, 100, 6000, 0), False),
    ("7c9e6679-7425-40de-944b-e07fc1f90ae7", T0 + 23 * H + 32 * 60000, "req_003", "claude-opus-4-1", (300, 900, 10000, 2000), False),
    ("7c9e6679-7425-40de-944b-e07fc1f90ae7", T0 + D + 9 * H, "req_004", "claude-haiku-4-5", (20, 80, 0, 0), True),
]
# effort written in the conversation file (the telemetry says "high" for the requests it reports)
CC_EFFORT = {"req_001": "high", "req_002": "high", "req_003": "high", "req_004": "medium"}
# cost per request as Claude Code's telemetry reports it (req_004 has no event: telemetry was down)
CC_TELEMETRY_COST = {"req_001": 0.021, "req_002": 0.012, "req_003": 0.25}


def _iso(ms):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + ".%03dZ" % (ms % 1000)


def make_claude(root):
    """~/.claude-like tree (projects, commands, skills) under `root`; returns the paths."""
    projects, cmds, skills = (os.path.join(root, d) for d in ("projects", "commands", "skills"))
    for d in (projects, cmds, skills):
        os.makedirs(d, exist_ok=True)
    lines = {}
    for sid, (folder, cwd) in CC_SESSIONS.items():
        os.makedirs(os.path.join(projects, folder), exist_ok=True)
        lines[sid] = []
    first = {sid: True for sid in CC_SESSIONS}
    for n, (sid, ts, req, model, (i, o, cr, cc), side) in enumerate(CC_ASSISTANT):
        cwd = CC_SESSIONS[sid][1]
        if side:
            continue
        if first[sid]:
            lines[sid].append({"type": "custom-title", "customTitle": "Sesión %s" % sid[:4], "sessionId": sid})
            first[sid] = False
        lines[sid].append({"type": "user", "sessionId": sid, "cwd": cwd, "timestamp": _iso(ts - 2000), "uuid": "u%d" % n,
                           "promptId": "p%d" % n, "message": {"role": "user", "content": "haz la tarea %d" % n}})
        content = [{"type": "text", "text": "ok"}]
        if n == 0:
            content += [{"type": "tool_use", "id": "tu_read", "name": "Read", "input": {"file_path": "a.py"}},
                        {"type": "tool_use", "id": "tu_edit", "name": "Edit", "input": {"file_path": "a.py"}},
                        {"type": "tool_use", "id": "tu_skill", "name": "Skill", "input": {"skill": "pdf"}}]
        lines[sid].append({"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": _iso(ts), "requestId": req,
                           "uuid": "a%d" % n, "effort": CC_EFFORT.get(req), "message": {"id": "msg_%s" % req, "role": "assistant", "model": model, "content": content,
                                                          "usage": {"input_tokens": i, "output_tokens": o,
                                                                    "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}})
        if n == 0:
            lines[sid].append({"type": "user", "sessionId": sid, "cwd": cwd, "timestamp": _iso(ts + 500), "uuid": "r0",
                               "message": {"role": "user", "content": [
                                   {"type": "tool_result", "tool_use_id": "tu_read", "content": "x"}]}})
            lines[sid].append({"type": "user", "sessionId": sid, "cwd": cwd, "timestamp": _iso(ts + 700), "uuid": "r1",
                               "permissionDecision": {"decision": "accept", "source": "user_temporary"},
                               "message": {"role": "user", "content": [
                                   {"type": "tool_result", "tool_use_id": "tu_edit", "is_error": True,
                                    "content": "String to replace not found in file."}]}})
    # a custom command and a compaction in the second session
    sid2 = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    lines[sid2].insert(1, {"type": "user", "sessionId": sid2, "cwd": CC_SESSIONS[sid2][1], "timestamp": _iso(T0 + 23 * H + 31 * 60000),
                           "uuid": "cmd1", "promptId": "p2",
                           "message": {"role": "user", "content": "<command-message>revisa</command-message>\n<command-name>/revisa</command-name>"}})
    lines[sid2].append({"type": "system", "sessionId": sid2, "timestamp": _iso(T0 + D + 8 * H), "compactMetadata":
                        {"preTokens": 150000, "postTokens": 20000, "trigger": "auto"}})
    for sid, rows in lines.items():
        folder = CC_SESSIONS[sid][0]
        with open(os.path.join(projects, folder, sid + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    # the subagent's messages live in <session>/subagents/<agent>.jsonl
    for sid, ts, req, model, (i, o, cr, cc), side in CC_ASSISTANT:
        if not side:
            continue
        folder, cwd = CC_SESSIONS[sid]
        sub = os.path.join(projects, folder, sid, "subagents")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "agent-explorer.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "sessionId": sid, "cwd": cwd, "timestamp": _iso(ts), "requestId": req,
                                "isSidechain": True, "uuid": "s1", "effort": CC_EFFORT.get(req),
                                "message": {"id": "msg_" + req, "role": "assistant", "model": model, "content": [],
                                            "usage": {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr,
                                                      "cache_creation_input_tokens": cc}}}, separators=(",", ":")) + "\n")
    with open(os.path.join(cmds, "revisa.md"), "w", encoding="utf-8") as f:
        f.write("Revisa el código\n")
    os.makedirs(os.path.join(skills, "pdf"), exist_ok=True)
    with open(os.path.join(skills, "pdf", "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: pdf\n---\n")
    return {"projects": projects, "commands": cmds, "skills": skills}
