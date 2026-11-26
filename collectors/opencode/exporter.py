"""Prometheus exporter for OpenCode usage.

Reads OpenCode's SQLite database (read-only) and publishes cost and token
totals. The queries are written for OpenCode 1.x's `session`, `message` and
`part` tables; on an OpenCode 2.x database `oc_schema` presents its new tables
in that shape. The context limit of each model comes from OpenCode's models.dev
catalog (`catalog`: models.json in 1.x, the database in 2.x).
"""
import calendar
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import report_page
import ledger_source
import api_prices
import catalog
import oc_schema
import session_page
from common import security
from common import ledger as common_ledger
from coach import index as coach_index, metrics as coach_metrics, render as coach_render, report as coach_report

DB = os.environ.get("OPENCODE_DB", "/data/opencode.db")
COMMANDS_DIR = os.environ.get("OPENCODE_COMMANDS_DIR", "/commands")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000/d/opencode-usage")
PORT = int(os.environ.get("PORT", "9101"))
CONTEXT_SESSIONS = int(os.environ.get("CONTEXT_SESSIONS", "5"))
# "provider/model=tokens,..." for models the cache does not know (custom providers, Copilot aliases)
CONTEXT_LIMITS = os.environ.get("CONTEXT_LIMITS", "")
TOKEN_TYPES = {
    "input": "$.tokens.input",
    "output": "$.tokens.output",
    "reasoning": "$.tokens.reasoning",
    "cache_read": "$.tokens.cache.read",
    "cache_write": "$.tokens.cache.write",
}

_SUMS = ", ".join(
    f"coalesce(sum(json_extract(m.data,'{p}')),0)" for p in TOKEN_TYPES.values()
)
_TOTAL = "(" + " + ".join(
    f"coalesce(sum(json_extract(m.data,'{p}')),0)" for p in TOKEN_TYPES.values()
) + ")"

# worktree "/" is OpenCode's "no project" placeholder
TOTALS = f"""
select coalesce(json_extract(m.data,'$.providerID'),'unknown'),
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
group by 1,2,3,4
"""

_limits = {"stamp": None, "data": {}}


def model_limits():
    """Context limits from the models.dev catalog, recomputed only when the catalog changes."""
    raw = catalog.load()
    if _limits["stamp"] != catalog.stamp():
        data = {}
        for prov, pdata in raw.items():
            for mid, mdata in (pdata.get("models") or {}).items():
                ctx = (mdata.get("limit") or {}).get("context")
                if ctx:
                    data[(prov, mid)] = int(ctx)
        _limits.update(stamp=catalog.stamp(), data=data)
    return _limits["data"]


_ROW_TOKENS = " + ".join("coalesce(json_extract(m.data,'%s'),0)" % p for p in TOKEN_TYPES.values())
_ZERO = "coalesce(json_extract(m.data,'$.cost'),0) = 0"
_ZERO_TOKENS = ", ".join(
    "coalesce(sum(case when %s then coalesce(json_extract(m.data,'%s'),0) else 0 end),0)" % (_ZERO, p) for p in TOKEN_TYPES.values())
MODEL_COSTS = f"""
select coalesce(json_extract(m.data,'$.providerID'),'unknown'),
       coalesce(json_extract(m.data,'$.modelID'),'unknown'),
       count(*), {_TOTAL}, coalesce(sum(json_extract(m.data,'$.cost')),0),
       sum(case when {_ZERO} and ({_ROW_TOKENS}) > 0 then 1 else 0 end),
       min(m.time_created), max(m.time_created), {_ZERO_TOKENS}
from message m
where json_extract(m.data,'$.role') = 'assistant'
group by 1,2
"""
_warned_models = set()
# Providers you pay with a subscription (informative: their messages are still valued at API price)
SUBSCRIPTION_PROVIDERS = {p.strip().lower() for p in os.environ.get("SUBSCRIPTION_PROVIDERS", "").split(",") if p.strip()}


def payment(provider):
    p = (provider or "").lower()
    if p in api_prices.LOCAL_PROVIDERS:
        return "local"
    return "suscripción" if p in SUBSCRIPTION_PROVIDERS else "por token"


def model_costs(c):
    """Per model: (provider, model, messages, tokens, cost OpenCode stored, messages with tokens but cost 0,
    first ms, last ms, price or None, flagged, price source, API-equivalent cost, payment).
    The API-equivalent cost adds tokens × price to the messages stored with cost 0 (api_prices).
    Flagged: it has such messages and no price is known for it anywhere in the models.dev catalog."""
    rows = []
    for prov, model, n, tok, stored, zero, first, last, *ztok in c.execute(MODEL_COSTS):
        price, src = api_prices.price(prov, model)
        extra = api_prices.cost(prov, model, ztok[0], ztok[1], ztok[2], ztok[3], ztok[4]) if zero else 0.0
        rows.append((prov, model, n, tok, stored, zero, first, last, price, bool(zero) and price is None, src,
                     stored + (extra or 0.0), payment(prov)))
    return sorted(rows, key=lambda r: -r[11])


def models_without_price(c):
    """provider/model -> messages stored with cost 0 that cannot be valued: no price for the model in the models.dev catalog."""
    found = {"%s/%s" % (r[0], r[1]): r[5] for r in model_costs(c) if r[9]}
    for model in sorted(set(found) - _warned_models):
        print("AVISO: %s no tiene precio en el catálogo de models.dev; sus %d mensajes con coste 0 no cuentan en el dashboard."
              % (model, found[model]), flush=True)
        _warned_models.add(model)
    return found


def prices_status():
    """Plain-text answer of /prices/missing: OK, or SIN PRECIO + models."""
    c = connect()
    try:
        missing = models_without_price(c)
    finally:
        c.close()
    if not missing:
        return "OK\n"
    return "SIN PRECIO\n" + "".join("  %s: %d mensajes sin coste\n" % (m, n) for m, n in sorted(missing.items()))


def prices_page():
    c = connect()
    try:
        rows = model_costs(c)
        models_without_price(c)
    finally:
        c.close()
    return session_page.render_prices(rows, GRAFANA_URL, catalog.available())


def context_limit(provider, model):
    overrides = {}
    for item in filter(None, (x.strip() for x in CONTEXT_LIMITS.split(","))):
        key, _, val = item.partition("=")
        if val.strip().isdigit():
            overrides[key.strip()] = int(val)
    limits = model_limits()
    # Copilot spells versions with dots and models.dev with hyphens, or the other way round
    for mid in (model, model.replace(".", "-"), model.replace("-", ".")):
        key = provider + "/" + mid
        if key in overrides:
            return overrides[key]
        if (provider, mid) in limits:
            return limits[(provider, mid)]
    return None


QUOTA_DIR = os.environ.get("OPENCODE_QUOTA_DIR", "/cache/quota-provider-state")
# The opencode-quota plugin names providers differently from OpenCode's own provider ids
QUOTA_PROVIDER_ALIASES = {"copilot": "github-copilot"}
_SCALE = {"": 1, "k": 1_000, "m": 1_000_000}


def _number(text, suffix):
    return float(text.replace(",", "")) * _SCALE[suffix.lower()]


def parse_amounts(right):
    """'22/7000' or '1.5k/5k' -> (22.0, 7000.0); None when the plugin shows something else."""
    m = re.match(r"^\s*([\d.,]+)\s*([kKmM]?)\s*/\s*([\d.,]+)\s*([kKmM]?)\s*$", right or "")
    if not m:
        return None
    try:
        return _number(m.group(1), m.group(2)), _number(m.group(3), m.group(4))
    except ValueError:
        return None


def read_quotas():
    """Quota of each provider, from the state files the opencode-quota plugin caches.

    A provider that reports several quotas is reduced to the one with the least left.
    """
    quotas, errors = {}, {}
    if not os.path.isdir(QUOTA_DIR):
        return quotas, errors
    for name in sorted(os.listdir(QUOTA_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(QUOTA_DIR, name), encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            continue
        provider = QUOTA_PROVIDER_ALIASES.get(state.get("providerId", ""), state.get("providerId", ""))
        if not provider:
            continue
        updated = (state.get("timestamp") or 0) / 1000
        result = state.get("result") or {}
        for entry in result.get("entries") or []:
            remaining = entry.get("percentRemaining")
            if remaining is None:
                continue
            current = quotas.get(provider)
            if current is None or remaining < current["remaining"]:
                reset = entry.get("resetTimeIso")
                try:
                    reset_ts = calendar.timegm(time.strptime(reset[:19], "%Y-%m-%dT%H:%M:%S")) if reset else None
                except ValueError:
                    reset_ts = None
                quotas[provider] = {"remaining": remaining, "amounts": parse_amounts(entry.get("right")),
                                    "reset": reset_ts, "updated": updated}
        for err in result.get("errors") or []:
            if provider not in quotas:
                errors[provider] = str(err.get("message") or "error")
    return quotas, errors


def human(n):
    if n >= 1_000_000:
        return ("%.2f" % (n / 1_000_000)).rstrip("0").rstrip(".") + "M"
    return "%dk" % round(n / 1000)


SKILL_CALLS = """
select p.id,
       date(p.time_created/1000,'unixepoch'),
       json_extract(p.data,'$.state.input.name'),
       json_extract(p.data,'$.state.status'),
       json_extract(m.data,'$.parentID'),
       coalesce(pr.worktree,''),
       coalesce(json_extract(m.data,'$.providerID'),'unknown'),
       coalesce(json_extract(m.data,'$.modelID'),'unknown'),
       coalesce(json_extract(m.data,'$.agent'),'unknown'),
       p.time_created
from part p
join message m on m.id = p.message_id
join session s on s.id = p.session_id
left join project pr on pr.id = s.project_id
where {ids} and json_extract(p.data,'$.type') = 'tool' and json_extract(p.data,'$.tool') = 'skill'
"""
# In SKILL_CALLS, USER_TEXTS and coach/index.py the id condition goes first: on OpenCode 2.x `part` is a
# view (oc_schema) and SQLite tests the conditions in order, so the parts already read are discarded
# before their JSON is built.

# A turn is every assistant message that answers the same user message
# A custom command leaves no mark in the database: OpenCode stores its template, already
# expanded, as the text of the user message. It is recognised by that template's opening.
USER_TEXTS = """
select p.id,
       date(p.time_created/1000,'unixepoch'),
       substr(json_extract(p.data,'$.text'), 1, ?),
       p.message_id,
       coalesce(pr.worktree,''),
       p.time_created,
       coalesce(json_extract(p.data,'$.synthetic'),0)
from part p
join message m on m.id = p.message_id
join session s on s.id = p.session_id
left join project pr on pr.id = s.project_id
where p.id > ? and p.id <= ?
  and json_extract(m.data,'$.role') = 'user' and json_extract(p.data,'$.type') = 'text'
"""

_commands = {"stamp": None, "templates": {}}


def command_templates():
    """The opening of each custom command's template, up to its first $ARGUMENTS."""
    try:
        names = [n for n in os.listdir(COMMANDS_DIR) if n.endswith(".md")]
        stamp = tuple(sorted((n, os.path.getmtime(os.path.join(COMMANDS_DIR, n))) for n in names))
    except OSError:
        return {}
    if _commands["stamp"] != stamp:
        found = {}
        for n in names:
            try:
                with open(os.path.join(COMMANDS_DIR, n), encoding="utf-8") as f:
                    body = re.sub(r"^---.*?---\s*", "", f.read(), count=1, flags=re.S).strip()
            except OSError:
                continue
            cut = body.find("$ARGUMENTS")
            opening = (body[:cut] if cut > 0 else body).strip()
            if len(opening) >= 10:
                found[n[:-3]] = opening
        _commands.update(stamp=stamp, templates=found)
    return _commands["templates"]


def match_command(text, templates):
    """The command whose template opens this text; the longest opening wins, a tie matches none."""
    text = text.lstrip()
    hits = sorted(((len(o), n) for n, o in templates.items() if text.startswith(o)), reverse=True)
    if not hits or (len(hits) > 1 and hits[0][0] == hits[1][0]):
        return None
    return hits[0][1]


# Finding skill calls means reading the `part` table, which holds every tool output and is
# slow to scan through a Docker bind mount. It is scanned once in the background and then
# only for parts newer than the last one seen, so a scrape never waits for it.
_skills = {"calls": {}, "pending": set(), "commands": {}, "prompts": {}, "last_id": "", "done": False}
# The opening of each prompt, for «Prompts más caros». Only in memory, never in Prometheus; the dashboard
# shows it or asks /data for asterisks (mask=prompt). PROMPT_TEXT=0 stops reading it.
PROMPT_TEXT = os.environ.get("PROMPT_TEXT", "1") != "0"
PROMPT_TEXT_CHARS = 300
_skills_lock = threading.Lock()


def refresh_skill_calls():
    c = connect()
    try:
        top = c.execute("select max(id) from part").fetchone()[0] or ""
        with _skills_lock:
            last, pending = _skills["last_id"], list(_skills["pending"])
        rows = c.execute(SKILL_CALLS.format(ids="p.id > ? and p.id <= ?"), (last, top)).fetchall()
        for pid in pending:  # calls that were still running the last time
            rows += c.execute(SKILL_CALLS.format(ids="p.id = ?"), (pid,)).fetchall()
        templates = command_templates()
        texts = []
        if templates or PROMPT_TEXT:
            width = max([len(o) + 1 for o in templates.values()] + [PROMPT_TEXT_CHARS * 4 if PROMPT_TEXT else 0])
            texts = c.execute(USER_TEXTS, (width, last, top)).fetchall()
    finally:
        c.close()
    with _skills_lock:
        for pid, day, text, message_id, wt, ts, synthetic in texts:
            name = match_command(text or "", templates) if templates else None
            if name and message_id not in _skills["commands"]:
                _skills["commands"][message_id] = (day, name, wt, ts)
            if PROMPT_TEXT and not synthetic and (text or "").strip() and message_id not in _skills["prompts"]:
                # a command shows as "/name", not as its expanded template
                _skills["prompts"][message_id] = "/" + name if name else " ".join(text.split())[:PROMPT_TEXT_CHARS]
        for pid, day, name, status, parent, wt, prov, model, agent, ts in rows:
            if not name:
                continue
            _skills["calls"][pid] = (day, name, status, parent, wt, prov, model, agent, ts)
            if status in ("pending", "running"):
                _skills["pending"].add(pid)
            else:
                _skills["pending"].discard(pid)
        _skills["last_id"], _skills["done"] = top, True


def skill_loop():
    woken, series_at = False, 0
    while True:
        try:
            refresh_skill_calls()
        except Exception as e:  # the next round retries; scrapes keep serving what is cached
            print("AVISO: fallo leyendo skills y comandos (%s)." % type(e).__name__, flush=True)
        if time.time() - series_at >= SERIES_EVERY:
            try:
                refresh_series()
                series_at = time.time()
            except Exception as e:
                print("AVISO: fallo leyendo opencode.db para /metrics (%s)." % type(e).__name__, flush=True)
        try:  # keep the improvement report's tool index warm, so /report.md answers quickly
            c = connect()
            try:
                coach_index.INDEX.refresh(c)
                # the data the findings panels and /data build from, cached so neither reads the database
                coach_metrics.refresh(c, sys.modules[__name__], force=woken)
            finally:
                c.close()
        except Exception as e:
            print("AVISO: fallo actualizando el informe (%s)." % type(e).__name__, flush=True)
        woken = coach_metrics.wait(30)


def project_name(worktree):
    name = os.path.basename(worktree.replace("\\", "/").rstrip("/"))
    return name or "global"


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


_schema_seen = {"version": None}


def connect():
    # mode=ro needs the -shm/-wal files; immutable=1 is the fallback when the
    # database sits on a read-only mount without them (it ignores the WAL).
    for suffix in ("?mode=ro", "?immutable=1"):
        try:
            c = sqlite3.connect("file:" + DB + suffix, uri=True, timeout=5)
            found = oc_schema.adapt(c)   # OpenCode 2.x: views with 1.x's tables (temporary, nothing is written)
            if found != _schema_seen["version"]:
                _schema_seen["version"] = found
                print("opencode.db: esquema de OpenCode %s%s." % (
                    "1.x" if found == "v1" else "2.x", "" if found == "v1" else " (leído con vistas de 1.x, ADR 0010)"), flush=True)
            c.execute("select 1 from message limit 1")
            return c
        except sqlite3.Error:
            continue
    raise sqlite3.OperationalError("cannot open " + DB)


RECENT_SESSIONS = """
select s.id, s.title, coalesce(p.worktree,'')
from session s left join project p on p.id = s.project_id
where s.parent_id is null
order by s.time_updated desc
limit ?
"""

LAST_ASSISTANT = """
select json_extract(data,'$.providerID'), json_extract(data,'$.modelID'),
       coalesce(json_extract(data,'$.tokens.input'),0),
       coalesce(json_extract(data,'$.tokens.output'),0) + coalesce(json_extract(data,'$.tokens.reasoning'),0),
       coalesce(json_extract(data,'$.tokens.cache.read'),0),
       coalesce(json_extract(data,'$.tokens.cache.write'),0)
from message
where session_id = ? and json_extract(data,'$.role') = 'assistant'
order by time_created desc
limit 8
"""


def context_usage(c):
    """Context size of the most recent sessions: tokens of their last answered message."""
    rows = []
    for sid, title, wt in c.execute(RECENT_SESSIONS, (CONTEXT_SESSIONS * 4,)):
        for prov, model, inp, out, cr, cw in c.execute(LAST_ASSISTANT, (sid,)):
            if inp + out + cr + cw > 0:  # skip the aborted or in-flight message that carries no tokens
                rows.append((sid, title or "", wt, prov or "unknown", model or "unknown", inp, out, cr, cw))
                break
        if len(rows) == CONTEXT_SESSIONS:
            break
    return rows


SERIES_EVERY = int(os.environ.get("SERIES_SECONDS", "60"))   # seconds between two readings of the database for /metrics
_series_cache = {"lines": [], "at": 0, "seconds": 0.0}
_series_lock = threading.Lock()


def refresh_series():
    """Read opencode.db for the Prometheus series (totals, models without a price, context of the recent
    sessions) and cache them. Called from the background thread: a scrape never opens the database,
    which on a Windows bind mount is slow."""
    out = []
    add = out.append
    started = time.time()
    c = connect()

    def labels(lab):
        return 'provider="%s",model="%s",agent="%s",project="%s"' % tuple(esc(x) for x in lab)

    try:
        # Cumulative totals, kept for anyone querying the counters directly
        cost, msgs, tok = {}, {}, {}
        for prov, model, agent, wt, n, cst, *toks in c.execute(TOTALS):
            lab = (prov, model, agent, project_name(wt))
            cost[lab] = cost.get(lab, 0) + cst
            msgs[lab] = msgs.get(lab, 0) + n
            for t, v in zip(TOKEN_TYPES, toks):
                tok[lab + (t,)] = tok.get(lab + (t,), 0) + v
        add("# TYPE opencode_cost_usd_total counter")
        for lab, v in cost.items():
            add("opencode_cost_usd_total{%s} %s" % (labels(lab), v))
        add("# TYPE opencode_tokens_total counter")
        for lab, v in tok.items():
            add('opencode_tokens_total{%s,type="%s"} %s' % (labels(lab[:4]), lab[4], v))
        add("# TYPE opencode_messages_total counter")
        for lab, v in msgs.items():
            add("opencode_messages_total{%s} %s" % (labels(lab), v))
        add("# TYPE opencode_model_without_price_messages gauge")
        for model, n in sorted(models_without_price(c).items()):
            add('opencode_model_without_price_messages{model="%s"} %s' % (esc(model), n))

        # Context window of the most recent sessions
        add("# TYPE opencode_context_tokens gauge")
        add("# TYPE opencode_context_limit_tokens gauge")
        for sid, title, wt, prov, model, inp, outp, cr, cw in context_usage(c):
            limit = context_limit(prov, model)
            name = (title[:48] + "…") if len(title) > 48 else title
            shown = "%s · %s (%s, %s)" % (project_name(wt), name or sid[:12], model, human(limit) if limit else "límite desconocido")
            lab = 'session="%s",label="%s",project="%s",provider="%s",model="%s"' % (
                esc(sid), esc(shown), esc(project_name(wt)), esc(prov), esc(model))
            for t, v in (("input", inp), ("cache_read", cr), ("cache_write", cw), ("output", outp)):
                add('opencode_context_tokens{%s,type="%s"} %s' % (lab, t, v))
            if limit:
                add('opencode_context_limit_tokens{%s} %s' % (lab, limit))
    finally:
        c.close()

    with _series_lock:
        _series_cache.update(lines=out, at=time.time(), seconds=round(time.time() - started, 3))


def collect():
    """What a scrape publishes: the cached series, the coach's, and the quotas (small files). No database."""
    started = time.time()
    with _series_lock:
        out = list(_series_cache["lines"])
        read_at, read_seconds = _series_cache["at"], _series_cache["seconds"]
    out.extend(coach_metrics.lines())
    add = out.append
    # Quota per provider, from the opencode-quota plugin's cache
    quotas, qerrors = read_quotas()
    add("# TYPE opencode_quota_remaining_ratio gauge")
    add("# TYPE opencode_quota_used gauge")
    add("# TYPE opencode_quota_limit gauge")
    add("# TYPE opencode_quota_reset_timestamp_seconds gauge")
    add("# TYPE opencode_quota_updated_timestamp_seconds gauge")
    for prov, q in quotas.items():
        lab = 'provider="%s"' % esc(prov)
        add("opencode_quota_remaining_ratio{%s} %s" % (lab, q["remaining"] / 100))
        if q["amounts"]:
            add("opencode_quota_used{%s} %s" % (lab, q["amounts"][0]))
            add("opencode_quota_limit{%s} %s" % (lab, q["amounts"][1]))
        if q["reset"]:
            add("opencode_quota_reset_timestamp_seconds{%s} %s" % (lab, q["reset"]))
        add("opencode_quota_updated_timestamp_seconds{%s} %s" % (lab, q["updated"]))
    add("# TYPE opencode_quota_error gauge")
    for prov, msg in qerrors.items():
        add('opencode_quota_error{provider="%s",message="%s"} 1' % (esc(prov), esc(msg)))

    add("# TYPE opencode_exporter_scrape_seconds gauge")
    add("opencode_exporter_scrape_seconds %s" % round(time.time() - started, 3))
    add("# TYPE opencode_series_read_seconds gauge")
    add("opencode_series_read_seconds %s" % read_seconds)
    add("# TYPE opencode_series_updated_timestamp_seconds gauge")
    add("opencode_series_updated_timestamp_seconds %d" % read_at)
    return "\n".join(out) + "\n"


_TOKENS = ", ".join(
    "coalesce(json_extract(data,'%s'),0)" % p for p in ("$.tokens.input", "$.tokens.output", "$.tokens.reasoning", "$.tokens.cache.read", "$.tokens.cache.write")
)


def session_detail(sid):
    """Everything the detail page shows about one session, or None when it does not exist."""
    c = connect()
    try:
        row = c.execute(
            "select s.id, s.title, s.parent_id, coalesce(p.worktree,''), s.summary_additions, s.summary_deletions, s.summary_files, "
            "s.time_created, s.time_updated from session s left join project p on p.id = s.project_id where s.id = ?", (sid,)).fetchone()
        if not row:
            return None
        msgs = []
        for t, prov, model, agent, cst, inp, outp, rsn, cr, cw in c.execute(
                "select time_created, json_extract(data,'$.providerID'), json_extract(data,'$.modelID'), json_extract(data,'$.agent'), "
                "coalesce(json_extract(data,'$.cost'),0), " + _TOKENS + " from message "
                "where session_id = ? and json_extract(data,'$.role') = 'assistant' order by time_created, id", (sid,)):
            tokens = {"input": inp, "output": outp + rsn, "cache_read": cr, "cache_write": cw}
            if sum(tokens.values()) > 0:  # skip the aborted or in-flight message that carries no tokens
                msgs.append({"t": t, "provider": prov or "unknown", "model": model or "unknown", "agent": agent or "unknown", "cost": cst, "tokens": tokens})
        tools, skills = {}, {}
        for tool, status, name in c.execute(
                "select json_extract(data,'$.tool'), json_extract(data,'$.state.status'), json_extract(data,'$.state.input.name') "
                "from part where session_id = ? and json_extract(data,'$.type') = 'tool'", (sid,)):
            entry = tools.setdefault(tool or "?", [0, 0])
            entry[0] += 1
            entry[1] += 1 if status == "error" else 0
            if tool == "skill" and name and status == "completed":
                skills[("skill", name)] = skills.get(("skill", name), 0) + 1
        templates = command_templates()
        if templates:
            width = max(len(o) for o in templates.values()) + 1
            seen = set()
            for text, mid in c.execute(
                    "select substr(json_extract(p.data,'$.text'), 1, ?), p.message_id from part p join message m on m.id = p.message_id "
                    "where p.session_id = ? and json_extract(m.data,'$.role') = 'user' and json_extract(p.data,'$.type') = 'text'", (width, sid)):
                name = match_command(text or "", templates)
                if name and mid not in seen:
                    seen.add(mid)
                    skills[("command", name)] = skills.get(("command", name), 0) + 1
        compactions = [t for (t,) in c.execute(
            "select m.time_created from part p join message m on m.id = p.message_id "
            "where p.session_id = ? and json_extract(p.data,'$.type') = 'compaction' order by m.time_created", (sid,))]
        children = []
        for cid, title, upd in c.execute("select id, title, time_updated from session where parent_id = ? order by time_updated desc", (sid,)).fetchall():
            cost = c.execute("select coalesce(sum(json_extract(data,'$.cost')),0) from message where session_id = ? and json_extract(data,'$.role') = 'assistant'", (cid,)).fetchone()[0]
            children.append((cid, title, cost, upd))
    finally:
        c.close()
    last = None
    limit = None
    if msgs:
        m = msgs[-1]
        last = dict(m["tokens"], model=m["model"], provider=m["provider"])
        limit = context_limit(m["provider"], m["model"])
    return {"id": row[0], "title": row[1], "parent": row[2], "project": project_name(row[3]), "additions": row[4] or 0,
            "deletions": row[5] or 0, "files": row[6] or 0, "created": row[7], "updated": row[8], "messages": msgs,
            "tools": tools, "skills": skills, "compactions": compactions, "children": children, "last": last, "limit": limit}


def sessions_list(since_ms, until_ms, projects, subagents):
    """Sessions created in the range, newest first, with their messages, tokens and cost."""
    c = connect()
    try:
        agg = {sid: (n, cost, tok) for sid, n, cost, tok in c.execute(
            "select session_id, count(*), coalesce(sum(json_extract(data,'$.cost')),0), " + " + ".join(
                "coalesce(json_extract(data,'%s'),0)" % p for p in ("$.tokens.input", "$.tokens.output", "$.tokens.reasoning", "$.tokens.cache.read", "$.tokens.cache.write")) +
            " from message where json_extract(data,'$.role') = 'assistant' group by session_id")}
        rows = []
        for sid, title, parent, wt, created, updated, agent in c.execute(
                "select s.id, s.title, s.parent_id, coalesce(p.worktree,''), s.time_created, s.time_updated, s.agent "
                "from session s left join project p on p.id = s.project_id where s.time_created between ? and ? order by s.time_updated desc",
                (since_ms, until_ms)):
            if parent and not subagents:
                continue
            proj = project_name(wt)
            if projects and proj not in projects:
                continue
            n, cost, tok = agg.get(sid, (0, 0, 0))
            rows.append((sid, title, parent, proj, created, updated, n, cost, tok, agent))
    finally:
        c.close()
    return rows


def list_range(query):
    """The [from, to] milliseconds that the dashboard's period selects: days back, or two UTC days."""
    def num(key, default):
        try:
            return int(query.get(key, [default])[0])
        except ValueError:
            return default
    now = int(time.time() * 1000)
    if "window" not in query and num("from", 0) > 10 ** 11:  # Grafana's ${__from}/${__to}, in ms (ADR 0002)
        start, end = num("from", 0), num("to", now)
        fmt = lambda ms: time.strftime("%Y-%m-%d", time.localtime(ms / 1000))
        return start, end, "del %s al %s" % (fmt(start), fmt(end))
    window = num("window", 36500)
    if window > 0:
        return now - window * 86400 * 1000, now, ("de los últimos %d días" % window) if window < 36500 else "de todo el historial"
    start, end = num("from", 0) * 1000, (num("to", 0) + 86399) * 1000
    return start, end, "del %s al %s (UTC)" % (time.strftime("%Y-%m-%d", time.gmtime(start / 1000)), time.strftime("%Y-%m-%d", time.gmtime((end - 86399000) / 1000)))


REPORT_CACHE_SECONDS = 120
# Older than this, the data a panel's report is built from is served anyway and read again in the background
SNAPSHOT_FRESH_SECONDS = 30
# Reports already built for the «Mejoras» panels, which ask several at a time per dashboard load
_REPORTS, _REPORTS_LOCK, _BUILD_LOCK = {}, threading.Lock(), threading.Lock()


def report_args(query):
    """Period, label, projects and anonymisation of a report request (window or from/to, project, anon)."""
    since, until, label = list_range(query)
    label = label.replace("de los ", "").replace("de todo el historial", "todo el historial")
    raw = ",".join(query.get("project", []))
    projects = {p for p in re.split(r"[,|]", raw) if p and p not in (".*", "All", "$__all")}
    return since, until, label, projects, query.get("anon", ["0"])[0] == "1"


def build_report(since, until, label, projects, anon, loaded=None):
    c = connect()
    try:
        return coach_report.build(c, sys.modules[__name__], since, until, label, projects or None, anon, loaded=loaded)
    finally:
        c.close()


def report_for(query, fresh=False):
    """The improvement report for a query string.

    `fresh` (the downloaded report) reads the database now. Otherwise (the dashboard's panels) the
    report is built from the data the background thread last read, at most about two minutes old,
    which takes a fraction of a second instead of seconds; if that data is older than
    SNAPSHOT_FRESH_SECONDS the thread is asked to read it again for the next request.
    """
    since, until, label, projects, anon = report_args(query)
    loaded, read_at = (None, 0) if fresh else coach_metrics.snapshot()
    if loaded is None:  # the downloaded report, or the thread has not finished its first reading
        return build_report(since, until, label, projects, anon)
    if time.time() - read_at > SNAPSHOT_FRESH_SECONDS:
        coach_metrics.request_refresh()
    key = (since // 60000, until // 60000, tuple(sorted(projects)), anon, read_at)
    with _BUILD_LOCK:
        now = time.time()
        with _REPORTS_LOCK:
            hit = _REPORTS.get(key)
            if hit and now - hit[0] < REPORT_CACHE_SECONDS:
                return hit[1]
        data = build_report(since, until, label, projects, anon, loaded)
        with _REPORTS_LOCK:
            _REPORTS[key] = (now, data)
            for k in [k for k, (t, _d) in _REPORTS.items() if now - t >= REPORT_CACHE_SECONDS]:
                del _REPORTS[k]
    return data


def _plain(text):
    """Finding text without Markdown marks, for Grafana tables."""
    return re.sub(r"[`*]", "", text or "")


def coach_rows(name, r):
    """Rows of one part of the report as a JSON array, for Grafana's Infinity datasource. None if unknown."""
    findings = r["findings"]
    rule = lambda d: "%s %s" % (d, coach_report.RULES.get(d, ""))
    if name == "summary":
        sev = Counter(f["severity"] for f in findings)
        return [{"hallazgos": len(findings), "alta": sev["alta"], "media": sev["media"], "baja": sev["baja"],
                 "impacto_usd": round(sum(f.get("impact_usd") or 0 for f in findings), 2),
                 "desde": r["period"]["from"], "hasta": r["period"]["to"]}]
    if name == "findings":
        return [{"id": f["id"], "severidad": f["severity"], "regla": rule(f["detector"]), "hallazgo": _plain(f["title"]),
                 "impacto_usd": f.get("impact_usd"), "casos": f.get("impact_count"),
                 "evidencia": _plain(f["evidence"]), "recomendacion": _plain(f["recommendation"])} for f in findings]
    if name == "rules":
        rows = {}
        for f in findings:
            row = rows.setdefault(f["detector"], {"regla": rule(f["detector"]), "hallazgos": 0, "alta": 0, "impacto_usd": 0.0})
            row["hallazgos"] += 1
            row["alta"] += f["severity"] == "alta"
            row["impacto_usd"] = round(row["impacto_usd"] + (f.get("impact_usd") or 0), 2)
        return sorted(rows.values(), key=lambda x: (-x["impacto_usd"], -x["hallazgos"]))
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if security.reject_unknown_host(self):
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/data" or parsed.path.startswith("/data/"):
            if coach_metrics.snapshot()[0] is None:  # first start: read now instead of answering empty
                coach_metrics.request_refresh()
            try:
                status, payload = ledger_source.LEDGER.handle(parsed.path, parsed.query)
            except Exception as e:
                status, payload = 500, {"error": str(e)}
            return common_ledger.respond(self, status, payload)
        if parsed.path.rstrip("/") == "/sessions":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                since, until, label = list_range(query)
                raw = ",".join(query.get("project", []))
                projects = {p for p in re.split(r"[,|]", raw) if p and p not in (".*", "All", "$__all")}
                subagents = query.get("subagents", ["0"])[0] == "1"
                rows = sessions_list(since, until, projects, subagents)
                note = "Sesiones creadas %s%s%s." % (label, ", proyecto: " + ", ".join(sorted(projects)) if projects else "", ", con subagentes" if subagents else "")
                other = {k: v for k, v in query.items() if k != "subagents"}
                other["subagents"] = ["0" if subagents else "1"]
                body = session_page.render_list(rows, GRAFANA_URL, subagents, note, "?" + urllib.parse.urlencode(other, doseq=True)).encode()
                self.send_response(200)
            except Exception as ex:
                body = ("Error: %s" % ex).encode()
                self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.rstrip("/") == "/report":
            self.report_view(parsed)
            return
        if parsed.path.rstrip("/") in ("/report.md", "/report.json"):
            self.report(parsed)
            return
        if parsed.path.startswith("/coach/"):
            try:
                rows = coach_rows(parsed.path[len("/coach/"):].strip("/"), report_for(urllib.parse.parse_qs(parsed.query)))
                status, body = (404, "[]") if rows is None else (200, json.dumps(rows, ensure_ascii=False))
            except Exception as e:
                status, body = 500, json.dumps({"error": str(e)})
            body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.rstrip("/") == "/health":  # healthcheck: the database must open
            try:
                connect().close()
                body, status = b"ok\n", 200
            except Exception as ex:
                body, status = ("error: %s\n" % ex).encode(), 503
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path.rstrip("/") in ("/prices", "/prices/missing"):
            page = parsed.path.rstrip("/") == "/prices"
            try:
                body, status = (prices_page() if page else prices_status()).encode(), 200
            except Exception as ex:
                body, status = ("Error: %s" % ex).encode(), 500
            self.send_response(status)
            self.send_header("Content-Type", ("text/html" if page and status == 200 else "text/plain") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        path = self.path.split("?")[0]
        if path.startswith("/session/"):
            sid = path[len("/session/"):].strip("/")
            try:
                data = session_detail(sid) if re.fullmatch(r"[A-Za-z0-9_]+", sid) else None
                body = (session_page.render(data, GRAFANA_URL) if data else session_page.not_found(GRAFANA_URL)).encode()
                self.send_response(200 if data else 404)
            except Exception as e:
                body = ("Error: %s" % e).encode()
                self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            body = collect().encode()
            self.send_response(200)
        except Exception as e:  # report the failure to Prometheus instead of an empty 200
            body = ("# exporter error: %s\n" % e).encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def report(self, parsed):
        """The improvement report for the dashboard's period and projects, to download and share with an AI."""
        as_json = parsed.path.rstrip("/").endswith(".json")
        try:
            data = report_for(urllib.parse.parse_qs(parsed.query), fresh=True)
            if as_json:
                body, ctype = coach_render.render_json(data).encode(), "application/json; charset=utf-8"
            else:
                body, ctype = coach_render.render(data).encode(), "text/markdown; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="opencode-informe-%s.%s"' % (
                time.strftime("%Y-%m-%d"), "json" if as_json else "md"))
        except Exception as e:
            body, ctype = ("Error: %s" % e).encode(), "text/plain; charset=utf-8"
            self.send_response(500)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def report_view(self, parsed):
        """The improvement report as a web page, opened from the dashboard, with a button to download its Markdown."""
        query = urllib.parse.parse_qs(parsed.query)
        anon = query.get("anon", ["0"])[0] == "1"
        other = {k: v for k, v in query.items() if k != "anon"}
        if not anon:
            other["anon"] = ["1"]
        anon_href = "?" + urllib.parse.urlencode(other, doseq=True)
        try:
            md = coach_render.render(report_for(query, fresh=True))
            filename = "opencode-informe-%s.md" % time.strftime("%Y-%m-%d")
            download = "/report.md" + ("?" + parsed.query if parsed.query else "")
            body = report_page.render(md, filename, GRAFANA_URL, download, anon, anon_href).encode()
            self.send_response(200)
        except Exception as ex:
            body = report_page.error("Error: %s" % ex, GRAFANA_URL).encode()
            self.send_response(500)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=skill_loop, daemon=True).start()
    # Threaded, so a session page or a report does not wait behind a scrape, and the other way round
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
