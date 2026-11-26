"""Reads OpenCode 2.x databases with the queries written for OpenCode 1.x.

OpenCode 2.x (2.4 and later) replaced the tables `session`, `message` and `part` with `session_v2`,
`session_message` and `session_part`, and changed the JSON of each row:

| 1.x                                   | 2.x                                                        |
|---------------------------------------|------------------------------------------------------------|
| message.data.role = user/assistant    | session_message.type = user/assistant/compaction/skill/…   |
| providerID, modelID                   | model.providerID, model.id                                 |
| parentID (the user message answered)  | none: the last `user` message before it (by `seq`)         |
| error.name (MessageAbortedError…)     | error.type (aborted…), error.message                       |
| part.data.tool, state.error (text)    | name, state.error.type / state.error.message               |
| skill tool input {name}               | skill tool input {id}; metadata.name                       |
| compaction: user msg + summary msg    | one `compaction` message with its own model, cost, tokens  |
| user text in a `text` part            | session_message.data.text                                  |

Assistant content lives in `session_part` (one row per text, reasoning or tool), except in messages
imported from 1.x, which keep it inline in `session_message.data.content`.

`adapt(conn)` creates TEMP views named `session`, `message` and `part` that present a 2.x database
in the 1.x shape, so every query of the collector and the coach keeps working unchanged. Temp views
live in the connection's own temporary schema: nothing is written to opencode.db, which stays
mounted read-only. They shadow the 1.x tables that OpenCode keeps after importing an old database.

Part ids of the views are `prt_<13-digit ms>_<message id>_<ordinal>`: they grow with the time a part
was created, as 1.x ids did, so the incremental scans by id (`id > last`) keep working.
"""

# A 1.x error name for each 2.x error type the coach treats specially (see coach/report.py)
_ERROR_NAME = """
case json_extract(m.data,'$.error.type')
  when 'aborted' then 'MessageAbortedError'
  when 'provider.auth' then 'ProviderAuthError'
  when 'provider.content-filter' then 'ContentFilterError'
  when 'provider.invalid-output' then 'MessageOutputLengthError'
  when 'provider.error' then 'APIError'
  when 'provider.invalid-request' then
    case when lower(coalesce(json_extract(m.data,'$.error.message'),'')) like '%context%' then 'ContextOverflowError'
         else 'provider.invalid-request' end
  else json_extract(m.data,'$.error.type')
end"""

_ZERO_TOKENS = '{"input":0,"output":0,"reasoning":0,"cache":{"read":0,"write":0}}'

# The user message a message answers: the last `user` message of the session before it
_PARENT = """(select u.id from main.session_message u
  where u.session_id = m.session_id and u.type = 'user' and u.seq < m.seq
  order by u.seq desc limit 1)"""

# One assistant answer (or compaction) in the 1.x shape
_ASSISTANT = """json_object(
  'role', 'assistant',
  'parentID', {parent},
  'agent', {agent},
  'providerID', json_extract(m.data,'$.model.providerID'),
  'modelID', json_extract(m.data,'$.model.id'),
  'cost', coalesce(json_extract(m.data,'$.cost'), 0),
  'tokens', json(coalesce(json_extract(m.data,'$.tokens'), '{zero}')),
  'error', case when json_extract(m.data,'$.error') is null then null else json_object('name', {error}) end,
  'summary', {summary},
  'time', json_object('created', m.time_created, 'completed', json_extract(m.data,'$.time.completed')))"""

MESSAGE_VIEW = """
create temp view message as
select m.id, m.session_id, m.time_created, m.time_updated,
  case m.type
    when 'assistant' then {assistant}
    when 'compaction' then {compaction}
    when 'skill' then json_object('role', 'skill', 'parentID', {parent},
                                  'time', json_object('created', m.time_created))
    else json_object('role', 'user', 'time', json_object('created', m.time_created))
  end as data
from main.session_message m
where m.type in ('user', 'synthetic', 'assistant', 'compaction', 'skill')
""".format(
    assistant=_ASSISTANT.format(parent=_PARENT, agent="json_extract(m.data,'$.agent')", error=_ERROR_NAME,
                                summary="json('false')", zero=_ZERO_TOKENS),
    # 1.x answered a compaction with an assistant message of agent "compaction" that carried its cost
    compaction=_ASSISTANT.format(parent="m.id", agent="'compaction'", error=_ERROR_NAME,
                                 summary="json('true')", zero=_ZERO_TOKENS),
    parent=_PARENT)

# The error of a tool call as 1.x wrote it: a plain text the coach classifies (coach/errors.py)
_TOOL_ERROR = """case
  when json_extract(c,'$.state.status') != 'error' then null
  when json_extract(c,'$.state.error.type') = 'permission.rejected' then
    case when json_extract(c,'$.state.error.message') like 'Permission denied:%'
         then 'The user has specified a rule which prevents this: ' || json_extract(c,'$.state.error.message')
         else 'The user rejected permission: ' || coalesce(json_extract(c,'$.state.error.message'),'') end
  when json_extract(c,'$.state.error.type') in ('tool.execution', 'unknown')
    then coalesce(json_extract(c,'$.state.error.message'), json_extract(c,'$.state.error.type'))
  else json_extract(c,'$.state.error.type') || ': ' || coalesce(json_extract(c,'$.state.error.message'),'')
end"""

# The input of a tool call; a call still streaming has its input as unparsed text, and the skill
# tool names its skill `id` (1.x: `name`), so `name` is added from the skill the call loaded
_TOOL_INPUT = """case
  when json_extract(c,'$.state.status') = 'streaming' or json_type(c,'$.state.input') != 'object' then json('{}')
  when json_extract(c,'$.name') = 'skill' then json_set(json_extract(c,'$.state.input'), '$.name',
       coalesce(json_extract(c,'$.state.input.name'), json_extract(c,'$.state.metadata.name'), json_extract(c,'$.state.input.id')))
  else json(json_extract(c,'$.state.input'))
end"""

# One element of an assistant's content (`c`) in the 1.x part shape
_CONTENT = """case json_extract(c,'$.type')
  when 'tool' then json_object(
    'type', 'tool',
    'callID', json_extract(c,'$.id'),
    'tool', json_extract(c,'$.name'),
    'state', json_object(
      'status', case json_extract(c,'$.state.status') when 'streaming' then 'pending' else json_extract(c,'$.state.status') end,
      'input', {input},
      'error', {error},
      'time', json_object('start', json_extract(c,'$.time.created'), 'end', json_extract(c,'$.time.completed'))))
  else json_object('type', json_extract(c,'$.type'), 'text', json_extract(c,'$.text'))
end""".format(input=_TOOL_INPUT, error=_TOOL_ERROR)


def _pid(ms, message, ordinal):
    return "'prt_' || printf('%013d', {}) || '_' || {} || '_' || printf('%05d', {})".format(ms, message, ordinal)


PART_VIEW = """
create temp view part as
-- assistant content, one row per text or tool (reasoning is not read)
select {pid_split} as id, p.message_id, p.session_id, p.time_created, p.time_updated,
       {content_split} as data
from main.session_part p
where p.type in ('tool', 'text')
union all
-- assistant content of messages imported from 1.x, kept inline
select {pid_inline} as id, m.id, m.session_id, m.time_created, m.time_updated,
       {content_inline} as data
from main.session_message m, json_each(m.data, '$.content') j
where m.type = 'assistant' and json_extract(j.value,'$.type') in ('tool', 'text')
  and not exists (select 1 from main.session_part sp where sp.message_id = m.id)
union all
-- what the user typed (synthetic: text OpenCode adds by itself), compactions and skills the user loaded
select {pid_msg} as id, m.id, m.session_id, m.time_created, m.time_updated,
  case m.type
    when 'user' then json_object('type', 'text', 'text', coalesce(json_extract(m.data,'$.text'), ''))
    when 'synthetic' then json_object('type', 'text', 'text', coalesce(json_extract(m.data,'$.text'), ''),
                                      'synthetic', json('true'))
    when 'compaction' then json_object('type', 'compaction', 'auto',
                                       case json_extract(m.data,'$.reason') when 'auto' then json('true') else json('false') end)
    else json_object('type', 'tool', 'tool', 'skill', 'state', json_object(
           'status', 'completed', 'input', json_object('name', json_extract(m.data,'$.name'))))
  end as data
from main.session_message m
where m.type in ('user', 'synthetic', 'compaction', 'skill')
""".format(
    pid_split=_pid("p.time_created", "p.message_id", "p.ordinal"),
    content_split=_CONTENT.replace("(c,", "(p.data,"),
    pid_inline=_pid("m.time_created", "m.id", "j.key"),
    content_inline=_CONTENT.replace("(c,", "(j.value,"),
    pid_msg=_pid("m.time_created", "m.id", "0"))

SESSION_VIEW = """
create temp view session as
select id, project_id, parent_id, title, directory, agent, model,
       summary_additions, summary_deletions, summary_files, time_created, time_updated
from main.session_v2
"""


def _tables(conn):
    return {name for (name,) in conn.execute("select name from main.sqlite_master where type = 'table'")}


def version(conn):
    """"v2" for an OpenCode 2.x database, "v1" for 1.x.

    After importing a 1.x database, OpenCode 2.x keeps the old tables beside the new ones: the new
    ones win, unless they are still empty while the old ones are not (the import has not run yet)."""
    tables = _tables(conn)
    if "session_v2" not in tables:
        return "v1"
    if "session" in tables and "message" in tables:
        new = conn.execute("select exists(select 1 from main.session_v2)").fetchone()[0]
        old = conn.execute("select exists(select 1 from main.session)").fetchone()[0]
        if old and not new:
            return "v1"
    return "v2"


def adapt(conn):
    """Make `conn` answer the 1.x queries. Returns the schema version found ("v1" or "v2")."""
    found = version(conn)
    if found == "v2":
        existing = {n for (n,) in conn.execute("select name from temp.sqlite_master where type = 'view'")}
        for name, ddl in (("session", SESSION_VIEW), ("message", MESSAGE_VIEW), ("part", PART_VIEW)):
            if name not in existing:
                conn.execute(ddl)
    return found
