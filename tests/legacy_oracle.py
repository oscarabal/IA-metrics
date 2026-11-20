"""Reference aggregates for the equivalence tests (ADR 0002).

Until November 2026 both collectors also published per-day and per-week Prometheus series
(claude_day_*, claude_coach_day_*/week_*, opencode_day_*, opencode_weekly_*). No dashboard read them
any more: the panels read /data. They were removed from the collectors and their code moved here,
unchanged, as an independent oracle: the tests check that /data gives the same figures as this
second implementation, computed straight from the index (Claude Code) or from opencode.db (OpenCode).
Not used at runtime.
"""
import calendar
import datetime
import time
from collections import Counter

WEEKS = 13


def day_of(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


_day = day_of


def _week(ms):
    d = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date()
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


_esc = esc


def _lab(**kw):
    return ",".join('%s="%s"' % (k, _esc(v)) for k, v in kw.items())


# ------------------------------------------------------------------ Claude Code
def claude_series(index, report):
    """Prometheus text of the former Claude Code per-day/per-week series."""
    ix = index.INDEX
    coach_out, coach_days = _claude_coach(report.snapshot(ix), index)
    out = list(coach_out)
    add = out.append
    with ix.lock:
        sessions = list(ix.sessions.values())
        uses, costs, created, days = {}, {}, {}, set()
        for s in sessions:
            if s["created"] and any(m[2] + m[3] + m[4] + m[5] > 0 for m in s["msgs"].values()):  # empty sessions are not counted, as in the list
                key = (day_of(s["created"]), s["project"])
                created[key] = created.get(key, 0) + 1
                days.add(key[0])
            for ts, name in s["commands"]:
                k = (day_of(ts), name, s["project"], "command")
                uses[k] = uses.get(k, 0) + 1
                days.add(k[0])
            for ts, name in s["skills"]:
                k = (day_of(ts), name, s["project"], "skill")
                uses[k] = uses.get(k, 0) + 1
                days.add(k[0])
            for m in s["msgs"].values():
                cost = ix.cost_of(m)
                if m[8] and cost is not None:
                    k = (day_of(m[0]), m[8], s["project"])
                    costs[k] = costs.get(k, 0) + cost
                    days.add(k[0])
        # cost of the turns each command launched (they share its prompt id), split by model and by origin: main thread, subagents, background calls
        launched = {}
        for s in sessions:
            for pid, (ts, name) in s["command_prompts"].items():
                launched[pid] = (day_of(ts), name, s["project"])
        by_command = {}
        for pid, model, origin, cost in list(ix.requests.values()):
            hit = launched.get(pid)
            if hit:
                k = hit + (model, origin)
                by_command[k] = by_command.get(k, 0) + cost
                days.add(hit[0])
        add("# TYPE claude_day_sessions gauge")
        for (day, proj), n in created.items():
            add('claude_day_sessions{day="%s",project="%s"} %s' % (day, esc(proj), n))
        add("# TYPE claude_day_skill_uses gauge")
        for (day, name, proj, kind), n in uses.items():
            add('claude_day_skill_uses{day="%s",skill="%s",project="%s",kind="%s"} %s' % (day, esc(name), esc(proj), kind, n))
        add("# TYPE claude_day_skill_cost_usd gauge")
        for (day, name, proj), v in costs.items():
            add('claude_day_skill_cost_usd{day="%s",skill="%s",project="%s"} %s' % (day, esc(name), esc(proj), v))
        add("# TYPE claude_day_command_cost_usd gauge")
        for (day, name, proj, model, origin), v in by_command.items():
            add('claude_day_command_cost_usd{day="%s",command="%s",project="%s",model="%s",origin="%s"} %s' % (day, esc(name), esc(proj), esc(model), esc(origin), v))
        days |= coach_days
        add("# TYPE claude_day_start_seconds gauge")
        for day in sorted(days):
            y, mo, d = (int(x) for x in day.split("-"))
            add('claude_day_start_seconds{day="%s"} %s' % (day, calendar.timegm((y, mo, d, 0, 0, 0))))
    return "\n".join(out) + "\n"


def _claude_coach(data, index):
    sessions, costs = data[:2]
    out, days = [], set()
    add = out.append
    week_from = (time.time() - WEEKS * 7 * 86400) * 1000
    calls_d, errs_d, comp_d, intr_d = Counter(), Counter(), Counter(), Counter()
    calls_w, errs_w, cost_w, msgs_w = Counter(), Counter(), Counter(), Counter()
    for s in sessions:
        proj = s["project"]
        for c in s["calls"]:
            if not c[0] or not c[5]:
                continue
            d = _day(c[0])
            days.add(d)
            calls_d[(d, c[1], c[2], proj)] += 1
            if c[5] == "error":
                errs_d[(d, c[1], c[6] or "other", c[2], proj)] += 1
            if c[0] >= week_from:
                w = _week(c[0])
                calls_w[(w, c[1], proj)] += 1
                if c[5] == "error":
                    errs_w[(w, c[1], c[6] or "other", proj)] += 1
        for comp in s["compactions"]:
            if comp[0]:
                comp_d[(_day(comp[0]), proj)] += 1
        for ts, _turn in s["interrupts"]:
            if ts:
                intr_d[(_day(ts), proj)] += 1
        for m in s["msgs"]:
            if m[0] >= week_from and m[2] + m[3] + m[4] + m[5] > 0:
                w = _week(m[0])
                cost_w[(w, m[1], proj)] += index.hybrid_cost(costs, m) or 0
                msgs_w[(w, m[1], proj)] += 1
    for name, data_, keys in (
            ("claude_coach_day_tool_calls", calls_d, ("day", "tool", "model", "project")),
            ("claude_coach_day_tool_errors", errs_d, ("day", "tool", "error_class", "model", "project")),
            ("claude_coach_day_compactions", comp_d, ("day", "project")),
            ("claude_coach_day_interrupts", intr_d, ("day", "project")),
            ("claude_coach_week_tool_calls", calls_w, ("week", "tool", "project")),
            ("claude_coach_week_tool_errors", errs_w, ("week", "tool", "error_class", "project")),
            ("claude_coach_week_cost_usd", cost_w, ("week", "model", "project")),
            ("claude_coach_week_messages", msgs_w, ("week", "model", "project"))):
        add("# TYPE %s gauge" % name)
        for k, v in data_.items():
            add("%s{%s} %s" % (name, _lab(**dict(zip(keys, k))), round(v, 6)))
    days.update(d for d, _p in comp_d)
    days.update(d for d, _p in intr_d)
    return out, days


# ------------------------------------------------------------------ OpenCode
_TOKEN_PATHS = ("$.tokens.input", "$.tokens.output", "$.tokens.reasoning", "$.tokens.cache.read", "$.tokens.cache.write")
_SUMS = ", ".join(f"coalesce(sum(json_extract(m.data,'{p}')),0)" for p in _TOKEN_PATHS)
_TOTAL = "(" + " + ".join(f"coalesce(sum(json_extract(m.data,'{p}')),0)" for p in _TOKEN_PATHS) + ")"
TOKEN_TYPES = ("input", "output", "reasoning", "cache_read", "cache_write")

PER_DAY = f"""
select date(m.time_created/1000,'unixepoch'),
       coalesce(json_extract(m.data,'$.providerID'),'unknown'),
       coalesce(json_extract(m.data,'$.modelID'),'unknown'),
       coalesce(json_extract(m.data,'$.agent'),'unknown'),
       coalesce(p.worktree,''),
       count(*),
       coalesce(sum(json_extract(m.data,'$.cost')),0),
       {_SUMS}
from message m
join session s on s.id = m.session_id
left join project p on p.id = s.project_id
where json_extract(m.data,'$.role') = 'assistant'
group by 1,2,3,4,5
"""

SESSIONS_PER_DAY = """
select date(s.time_created/1000,'unixepoch'), coalesce(p.worktree,''), count(*)
from session s left join project p on p.id = s.project_id
where s.parent_id is null
group by 1,2
"""

# Monday of the ISO week, so the dashboard can label weeks by a plain date
WEEKLY = f"""
select date(m.time_created/1000,'unixepoch','weekday 0','-6 days'),
       coalesce(p.worktree,''),
       coalesce(sum(json_extract(m.data,'$.cost')),0),
       {_TOTAL}
from message m
join session s on s.id = m.session_id
left join project p on p.id = s.project_id
where json_extract(m.data,'$.role') = 'assistant'
  and m.time_created >= ?
group by 1,2
"""


TURN_COST = """
select json_extract(data,'$.parentID'),
       coalesce(json_extract(data,'$.providerID'),'unknown'),
       coalesce(json_extract(data,'$.modelID'),'unknown'),
       coalesce(json_extract(data,'$.agent'),'unknown'),
       coalesce(sum(json_extract(data,'$.cost')),0)
from message
where json_extract(data,'$.role') = 'assistant'
group by 1,2,3,4
"""




def opencode_series(exporter, weeks=WEEKS):
    """Prometheus text of the former OpenCode per-day/per-week series, from opencode.db and the coach snapshot."""
    out = []
    add = out.append
    project_name, labels_esc = exporter.project_name, exporter.esc
    _skills_lock, _skills = exporter._skills_lock, exporter._skills

    def labels(lab):
        return 'provider="%s",model="%s",agent="%s",project="%s"' % tuple(labels_esc(x) for x in lab)

    def skill_usage(c):
        return _skill_usage(c, exporter)

    c = exporter.connect()
    try:
        # Per day, for the dashboard's date range
        day_cost, day_msgs, day_tok, days = {}, {}, {}, set()
        for day, prov, model, agent, wt, n, cst, *toks in c.execute(PER_DAY):
            lab = (day, prov, model, agent, project_name(wt))
            days.add(day)
            day_cost[lab] = day_cost.get(lab, 0) + cst
            day_msgs[lab] = day_msgs.get(lab, 0) + n
            for t, v in zip(TOKEN_TYPES, toks):
                day_tok[lab + (t,)] = day_tok.get(lab + (t,), 0) + v
        day_sess = {}
        for day, wt, n in c.execute(SESSIONS_PER_DAY):
            days.add(day)
            day_sess[(day, project_name(wt))] = day_sess.get((day, project_name(wt)), 0) + n

        def dl(lab):
            return 'day="%s",%s' % (lab[0], labels(lab[1:5]))

        add("# TYPE opencode_day_cost_usd gauge")
        for lab, v in day_cost.items():
            add("opencode_day_cost_usd{%s} %s" % (dl(lab), v))
        add("# TYPE opencode_day_messages gauge")
        for lab, v in day_msgs.items():
            add("opencode_day_messages{%s} %s" % (dl(lab), v))
        add("# TYPE opencode_day_tokens gauge")
        for lab, v in day_tok.items():
            add('opencode_day_tokens{%s,type="%s"} %s' % (dl(lab[:5]), lab[5], v))
        add("# TYPE opencode_day_sessions gauge")
        for (day, proj), v in day_sess.items():
            add('opencode_day_sessions{day="%s",project="%s"} %s' % (day, esc(proj), v))
        # Start of each UTC day as a sample value: PromQL cannot compare label
        # strings, so the dashboard filters days by comparing this value.
        add("# TYPE opencode_day_start_seconds gauge")
        for day in sorted(days):
            y, mo, d = (int(x) for x in day.split("-"))
            add('opencode_day_start_seconds{day="%s"} %s' % (day, calendar.timegm((y, mo, d, 0, 0, 0))))

        # Skills: activations and the cost of the turns that loaded them
        skill_acts, skill_cost, skill_acts_by, skill_cost_by = skill_usage(c)
        add("# TYPE opencode_day_skill_activations gauge")
        for (day, kind, name, proj, result), n in skill_acts.items():
            add('opencode_day_skill_activations{day="%s",kind="%s",skill="%s",project="%s",result="%s"} %s' % (day, kind, esc(name), esc(proj), result, n))
        add("# TYPE opencode_skill_scan_complete gauge")
        add("opencode_skill_scan_complete %s" % (1 if _skills["done"] else 0))
        add("# TYPE opencode_day_skill_cost_usd gauge")
        for (day, kind, name, proj), v in skill_cost.items():
            add('opencode_day_skill_cost_usd{day="%s",kind="%s",skill="%s",project="%s"} %s' % (day, kind, esc(name), esc(proj), v))
        add("# TYPE opencode_day_skill_detail_activations gauge")
        for (day, kind, name, proj, prov, model, agent, result), n in skill_acts_by.items():
            add('opencode_day_skill_detail_activations{day="%s",kind="%s",skill="%s",project="%s",provider="%s",model="%s",agent="%s",result="%s"} %s'
                % (day, kind, esc(name), esc(proj), esc(prov), esc(model), esc(agent), result, n))
        add("# TYPE opencode_day_skill_detail_cost_usd gauge")
        for (day, kind, name, proj, prov, model, agent), v in skill_cost_by.items():
            add('opencode_day_skill_detail_cost_usd{day="%s",kind="%s",skill="%s",project="%s",provider="%s",model="%s",agent="%s"} %s'
                % (day, kind, esc(name), esc(proj), esc(prov), esc(model), esc(agent), v))

        # Weekly trend per project, last weeks weeks
        add("# TYPE opencode_weekly_cost_usd gauge")
        add("# TYPE opencode_weekly_tokens gauge")
        since = int((time.time() - weeks * 7 * 86400) * 1000)
        wk_cost, wk_tok = {}, {}
        for week, wt, cst, total in c.execute(WEEKLY, (since,)):
            key = (week, project_name(wt))
            wk_cost[key] = wk_cost.get(key, 0) + cst
            wk_tok[key] = wk_tok.get(key, 0) + total
        for (week, proj), v in wk_cost.items():
            add('opencode_weekly_cost_usd{week="%s",project="%s"} %s' % (week, esc(proj), v))
            add('opencode_weekly_tokens{week="%s",project="%s"} %s' % (week, esc(proj), wk_tok[(week, proj)]))

    finally:
        c.close()
    loaded, _at = exporter.coach_metrics.snapshot()
    if loaded is not None:
        out.extend(_opencode_coach(loaded, weeks))
    return "\n".join(out) + "\n"


def _skill_usage(c, exporter):
    """Activations and cost per skill and per custom command, in total and by model and agent.

    The cost of a skill or command cannot be isolated, so it is the cost of the whole turn
    (every assistant message answering one user message) that loaded or ran it. When one
    turn loads several skills the cost is split equally among them. The by-model figures
    split that same cost by the model and agent that answered; an activation is credited to
    the model and agent of the message that loaded the skill, or, for a command, to the one
    that spent most in the turn it launched.
    """
    turns = {}  # user message -> {(provider, model, agent): cost}
    for parent, prov, model, agent, cost in c.execute(TURN_COST):
        turns.setdefault(parent, {})[(prov, model, agent)] = cost
    turn_cost = {parent: sum(parts.values()) for parent, parts in turns.items()}
    project_name = exporter.project_name
    with exporter._skills_lock:
        calls = list(exporter._skills["calls"].values())
        commands = list(exporter._skills["commands"].items())
    activations, cost, acts_by, cost_by = {}, {}, {}, {}
    pending_turns = {}
    for day, name, status, parent, wt, prov, model, agent, _ts in calls:
        if status in ("pending", "running"):
            continue
        proj = project_name(wt)
        result = "ok" if status == "completed" else "error"
        key = (day, "skill", name, proj, result)
        activations[key] = activations.get(key, 0) + 1
        dkey = (day, "skill", name, proj, prov, model, agent, result)
        acts_by[dkey] = acts_by.get(dkey, 0) + 1
        if result == "ok" and parent:
            pending_turns.setdefault(parent, (day, proj, set()))[2].add(name)
    for parent, (day, proj, names) in pending_turns.items():
        share = turn_cost.get(parent, 0) / len(names)
        for name in names:
            key = (day, "skill", name, proj)
            cost[key] = cost.get(key, 0) + share
            for (prov, model, agent), part in turns.get(parent, {}).items():
                dkey = (day, "skill", name, proj, prov, model, agent)
                cost_by[dkey] = cost_by.get(dkey, 0) + part / len(names)
    for message_id, (day, name, wt, _ts) in commands:
        proj = project_name(wt)
        key = (day, "command", name, proj, "ok")
        activations[key] = activations.get(key, 0) + 1
        ckey = (day, "command", name, proj)
        cost[ckey] = cost.get(ckey, 0) + turn_cost.get(message_id, 0)
        parts = turns.get(message_id, {})
        main = max(parts, key=parts.get) if parts else ("unknown", "unknown", "unknown")
        dkey = (day, "command", name, proj) + main + ("ok",)
        acts_by[dkey] = acts_by.get(dkey, 0) + 1
        for (prov, model, agent), part in parts.items():
            dkey = (day, "command", name, proj, prov, model, agent)
            cost_by[dkey] = cost_by.get(dkey, 0) + part
    return activations, cost, acts_by, cost_by



def _opencode_coach(loaded, weeks):
    out = []
    add = out.append
    msgs, sessions, calls, compactions = loaded
    by_id = {m.id: m for m in msgs}
    project = lambda sid: (sessions.get(sid) or {}).get("project", "global")
    week_from = (time.time() - weeks * 7 * 86400) * 1000

    # messages: interrupted answers by day; cost and messages by week and agent
    aborted_day, aborted_week = Counter(), Counter()
    agent_cost, agent_msgs = Counter(), Counter()
    for m in msgs:
        if m.role != "assistant":
            continue
        proj = project(m.session)
        if m.error == "MessageAbortedError":
            aborted_day[(_day(m.time), m.agent, proj)] += 1
        if m.time >= week_from:
            wk = _week(m.time)
            agent_cost[(wk, m.agent, proj)] += m.cost
            agent_msgs[(wk, m.agent, proj)] += 1
            if m.error == "MessageAbortedError":
                aborted_week[(wk, proj)] += 1

    add("# TYPE opencode_day_aborted gauge")
    for (day, agent, proj), n in aborted_day.items():
        add("opencode_day_aborted{%s} %d" % (_lab(day=day, agent=agent, project=proj), n))
    add("# TYPE opencode_weekly_agent_cost_usd gauge")
    for (wk, agent, proj), v in agent_cost.items():
        add("opencode_weekly_agent_cost_usd{%s} %s" % (_lab(week=wk, agent=agent, project=proj), v))
    add("# TYPE opencode_weekly_agent_messages gauge")
    for (wk, agent, proj), n in agent_msgs.items():
        add("opencode_weekly_agent_messages{%s} %d" % (_lab(week=wk, agent=agent, project=proj), n))
    add("# TYPE opencode_weekly_aborted gauge")
    for (wk, proj), n in aborted_week.items():
        add("opencode_weekly_aborted{%s} %d" % (_lab(week=wk, project=proj), n))

    if True:  # only called once the index is ready
        tc_day, te_day, tc_week, te_week = Counter(), Counter(), Counter(), Counter()
        for c in calls:
            if c.status in ("pending", "running"):
                continue
            m = by_id.get(c.message)
            model = m.model if m else "unknown"
            proj = project(c.session)
            day = _day(c.time)
            tc_day[(day, c.tool, model, proj)] += 1
            if c.status == "error":
                te_day[(day, c.tool, c.error_class, model, proj)] += 1
            if c.time >= week_from:
                wk = _week(c.time)
                tc_week[(wk, c.tool, proj)] += 1
                if c.status == "error":
                    te_week[(wk, c.tool, c.error_class, proj)] += 1
        comp_day, comp_week = Counter(), Counter()
        for sess, _mid, t in compactions:
            comp_day[(_day(t), project(sess))] += 1
            if t >= week_from:
                comp_week[(_week(t), project(sess))] += 1

        add("# TYPE opencode_day_tool_calls gauge")
        for (day, tool, model, proj), n in tc_day.items():
            add("opencode_day_tool_calls{%s} %d" % (_lab(day=day, tool=tool, model=model, project=proj), n))
        add("# TYPE opencode_day_tool_errors gauge")
        for (day, tool, cls, model, proj), n in te_day.items():
            add("opencode_day_tool_errors{%s} %d" % (_lab(day=day, tool=tool, error_class=cls, model=model, project=proj), n))
        add("# TYPE opencode_day_compactions gauge")
        for (day, proj), n in comp_day.items():
            add("opencode_day_compactions{%s} %d" % (_lab(day=day, project=proj), n))
        add("# TYPE opencode_weekly_tool_calls gauge")
        for (wk, tool, proj), n in tc_week.items():
            add("opencode_weekly_tool_calls{%s} %d" % (_lab(week=wk, tool=tool, project=proj), n))
        add("# TYPE opencode_weekly_tool_errors gauge")
        for (wk, tool, cls, proj), n in te_week.items():
            add("opencode_weekly_tool_errors{%s} %d" % (_lab(week=wk, tool=tool, error_class=cls, project=proj), n))
        add("# TYPE opencode_weekly_compactions gauge")
        for (wk, proj), n in comp_week.items():
            add("opencode_weekly_compactions{%s} %d" % (_lab(week=wk, project=proj), n))

    return out
