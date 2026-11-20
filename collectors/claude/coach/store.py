"""Small SQLite store so the history does not depend on Loki's 30 days or on a restart.

It keeps only metadata: each request (cost, model, query source, effort, session and output tokens), each
tool event (tool, session, bytes returned, permission decision) and an archive of each session's index entry (ADR 0002) so its usage survives Claude
Code deleting the conversation file (cleanupPeriodDays, 30 days by default). Never any text, titles or
paths, nor the tool parameters. If the volume is missing it falls back to memory.
"""
import json
import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("COACH_DB", "/state/coach.db")
# Days of history kept; 0 keeps everything. Older requests, tool events and archived sessions are deleted.
RETENTION_DAYS = int(os.environ.get("COACH_RETENTION_DAYS", "0") or 0)
MAINTAIN_EVERY = 86400

SCHEMA = """
create table if not exists request_cost (
    request_id text primary key, prompt_id text, model text, origin text, cost real, ts integer);
create table if not exists tool_event (
    tool_use_id text, kind text, ts integer, session_id text, tool text, bytes integer, decision text, source text,
    primary key (tool_use_id, kind));
drop table if exists daily;
create table if not exists session_archive (
    session_id text primary key, updated integer, data text);
"""

# Index fields that are text or paths: never archived (privacy boundary)
_NOT_ARCHIVED = ("title", "cwd", "branch", "prompts")
_SETS = ("errored", "seen_commands", "agents")


def _pack(s):
    d = {k: v for k, v in s.items() if k not in _NOT_ARCHIVED}
    for k in _SETS:
        d[k] = sorted(d.get(k) or ())
    return json.dumps(d, separators=(",", ":"))


def _unpack(text):
    d = json.loads(text)
    for k in _SETS:
        d[k] = set(d.get(k) or ())
    for k in _NOT_ARCHIVED:
        d[k] = {} if k == "prompts" else ""
    d["command_prompts"] = {pid: tuple(v) for pid, v in (d.get("command_prompts") or {}).items()}
    for k in ("commands", "skills", "compactions", "interrupts"):
        d[k] = [tuple(x) for x in d.get(k) or []]
    d["archived"] = True
    return d


def session_ids_on_disk(root):
    """Session ids that still have a conversation file: <project>/<id>.jsonl or <project>/<id>/subagents/*.jsonl."""
    ids = set()
    for folder, _dirs, names in os.walk(root):
        rel = os.path.relpath(folder, root).replace(os.sep, "/").split("/")
        for name in names:
            if name.endswith(".jsonl"):
                ids.add(rel[1] if len(rel) >= 3 and rel[2] == "subagents" else name[:-6])
    return ids


class Store:
    def __init__(self, path=DB_PATH):
        self.lock = threading.Lock()
        self.persistent = True
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.executescript(SCHEMA)
        except (OSError, sqlite3.Error):
            self.persistent = False
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("pragma table_info(request_cost)")}
        for col, kind in (("session_id", "text"), ("effort", "text"), ("output_tokens", "integer")):
            if col not in cols:  # stores created before these columns existed
                self.conn.execute("alter table request_cost add column %s %s" % (col, kind))
        self.conn.commit()
        self.saved = set()
        self.need_meta = set()   # stored requests still without session and effort
        self.saved_tools = set()
        self.archived = {}       # session id -> its "updated" when last archived
        self.maintained_at = time.time()   # first maintenance a day after starting, not on every restart

    # ---------------------------------------------------------------- request costs
    def restore(self, ix):
        """Put the stored request costs back into the index, so old sessions keep their cost after a restart."""
        with self.lock:
            rows = self.conn.execute("select request_id, prompt_id, model, origin, cost, ts, session_id, effort, output_tokens "
                                     "from request_cost").fetchall()
            tools = self.conn.execute("select tool_use_id, kind, ts, session_id, tool, bytes, decision, source from tool_event").fetchall()
        with ix.lock:
            for rid, pid, model, origin, cost, ts, sid, effort, out in rows:
                ix.costs.setdefault(rid, cost)
                ix.requests.setdefault(rid, (pid or "", model or "unknown", origin or "unknown", cost))
                if ts:
                    ix.request_ts.setdefault(rid, ts)
                if sid is None:
                    self.need_meta.add(rid)
                else:
                    ix.request_meta.setdefault(rid, (sid, effort or "", out or 0))
                self.saved.add(rid)
            for tid, kind, ts, sid, tool, size, dec, src in tools:
                ix.tool_events.setdefault((tid, kind), (ts, sid, tool, size, dec, src))
                self.saved_tools.add((tid, kind))
        return len(rows)

    def save_requests(self, ix):
        with ix.lock:
            new = [(rid, req, ix.request_ts.get(rid), ix.request_meta.get(rid)) for rid, req in ix.requests.items() if rid not in self.saved]
            late = [(rid, ix.request_meta[rid]) for rid in self.need_meta if rid in ix.request_meta]
            tools = [(k, v) for k, v in ix.tool_events.items() if k not in self.saved_tools]
        if not (new or late or tools):
            return 0
        with self.lock:
            self.conn.executemany(
                "insert or ignore into request_cost (request_id, prompt_id, model, origin, cost, ts, session_id, effort, output_tokens) "
                "values (?,?,?,?,?,?,?,?,?)",
                [(rid, pid, model, origin, cost, ts) + (tuple(meta) if meta else (None, None, None))
                 for rid, (pid, model, origin, cost), ts, meta in new])
            self.conn.executemany("update request_cost set session_id = ?, effort = ?, output_tokens = ? where request_id = ?",
                                  [(sid, eff, out, rid) for rid, (sid, eff, out) in late])
            self.conn.executemany("insert or replace into tool_event values (?,?,?,?,?,?,?,?)",
                                  [(tid, kind) + tuple(v) for (tid, kind), v in tools])
            self.conn.commit()
        self.saved.update(rid for rid, _req, _ts, meta in new)
        self.need_meta.update(rid for rid, _req, _ts, meta in new if not meta)
        self.need_meta.difference_update(rid for rid, _m in late)
        self.saved_tools.update(k for k, _v in tools)
        return len(new) + len(late) + len(tools)

    # ---------------------------------------------------------------- session archive (ADR 0002)
    def archive_sessions(self, ix):
        """Store the sessions that changed since the last call. Returns how many."""
        with ix.lock:
            changed = [(sid, s["updated"], _pack(s)) for sid, s in ix.sessions.items()
                       if not s.get("archived") and self.archived.get(sid) != s["updated"]]
        if not changed:
            return 0
        with self.lock:
            self.conn.executemany("insert or replace into session_archive values (?,?,?)", changed)
            self.conn.commit()
        self.archived.update((sid, upd) for sid, upd, _d in changed)
        return len(changed)

    def restore_sessions(self, ix, root):
        """Put back the archived sessions whose conversation file no longer exists. Returns how many.

        A session whose file is still there is left to the index, which reads it from the start: restoring
        it too would count its compactions and skills twice."""
        on_disk = session_ids_on_disk(root)
        with self.lock:
            rows = self.conn.execute("select session_id, updated, data from session_archive").fetchall()
        n = 0
        with ix.lock:
            for sid, upd, data in rows:
                self.archived[sid] = upd
                if sid in on_disk or sid in ix.sessions:
                    continue
                try:
                    ix.sessions[sid] = _unpack(data)
                    n += 1
                except (ValueError, TypeError):
                    continue
        return n

    # ---------------------------------------------------------------- maintenance
    def maintain(self, now=None):
        """Once a day: drop what is older than COACH_RETENTION_DAYS (0, the default, keeps everything) and
        compact the file. Returns the rows deleted, or None when it was not due."""
        now = now or time.time()
        if now - self.maintained_at < MAINTAIN_EVERY:
            return None
        self.maintained_at = now
        deleted = 0
        with self.lock:
            if RETENTION_DAYS > 0:
                cutoff = int((now - RETENTION_DAYS * 86400) * 1000)
                for sql in ("delete from request_cost where ts is not null and ts < ?",
                            "delete from tool_event where ts is not null and ts < ?",
                            "delete from session_archive where updated < ?"):
                    deleted += self.conn.execute(sql, (cutoff,)).rowcount
                self.conn.commit()
            if self.persistent:
                self.conn.execute("vacuum")
        return deleted


STORE = None


def get():
    global STORE
    if STORE is None:
        STORE = Store()
    return STORE
