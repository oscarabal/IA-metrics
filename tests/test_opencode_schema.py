"""oc_schema and catalog: reading OpenCode 2.x databases with the 1.x queries."""
import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("opencode")
import catalog  # noqa: E402
import oc_schema  # noqa: E402

SCHEMA_V2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode_v2_schema.sql")
V1_TABLES = """
create table session(id text primary key, project_id text, parent_id text, title text, time_created int, time_updated int);
create table message(id text primary key, session_id text, time_created int, time_updated int, data text);
create table part(id text primary key, message_id text, session_id text, time_created int, time_updated int, data text);
"""


def database(name, v1=False, v2=False):
    path = os.path.join(helpers.tmpdir(), name)
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path)
    if v1:
        c.executescript(V1_TABLES)
    if v2:
        with open(SCHEMA_V2, encoding="utf-8") as f:
            c.executescript(f.read())
    return path, c


class SchemaVersion(unittest.TestCase):
    def test_v1(self):
        _p, c = database("v1.db", v1=True)
        self.assertEqual(oc_schema.adapt(c), "v1")
        self.assertEqual(c.execute("select count(*) from temp.sqlite_master").fetchone()[0], 0)

    def test_v2_fresh(self):
        _p, c = database("v2.db", v2=True)
        self.assertEqual(oc_schema.adapt(c), "v2")
        for t in ("session", "message", "part"):
            self.assertEqual(c.execute("select count(*) from %s" % t).fetchone()[0], 0)
        self.assertEqual(oc_schema.adapt(c), "v2")   # a second call reuses the views

    def test_v1_imported_by_v2(self):
        """OpenCode 2.x keeps the 1.x tables after importing them: the 2.x ones are read, not the old ones."""
        _p, c = database("both.db", v1=True, v2=True)
        c.execute("insert into session values('ses_old','p',null,'vieja',1,1)")
        c.execute("insert into message values('msg_old','ses_old',1,1,'{\"role\":\"assistant\",\"cost\":9}')")
        # before the import: the old tables hold everything, the new ones nothing
        self.assertEqual(oc_schema.version(c), "v1")
        c.execute("insert into project(id,worktree,time_created,time_updated,sandboxes) values('p','/w',1,1,'[]')")
        c.execute("insert into session_v2(id,project_id,slug,directory,version,time_created,time_updated) "
                  "values('ses_new','p','s','/w','2.4.2',2,2)")
        c.execute("insert into session_message values('msg_new','ses_new','assistant',0,2,2,?)",
                  (json.dumps({"agent": "build", "model": {"providerID": "anthropic", "id": "m"}, "content": [], "cost": 1.5,
                               "tokens": {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                               "time": {"created": 2}}),))
        self.assertEqual(oc_schema.adapt(c), "v2")
        self.assertEqual(c.execute("select id from session").fetchall(), [("ses_new",)])
        self.assertEqual(c.execute("select sum(json_extract(data,'$.cost')) from message").fetchone()[0], 1.5)

    def test_inline_content_of_imported_messages(self):
        """Messages imported from 1.x keep their content inline; new ones in session_part. Both are parts."""
        _p, c = database("inline.db", v2=True)
        c.execute("insert into project(id,worktree,time_created,time_updated,sandboxes) values('p','/w',1,1,'[]')")
        c.execute("insert into session_v2(id,project_id,slug,directory,version,time_created,time_updated) "
                  "values('s','p','s','/w','2.4.2',1,1)")
        tool = {"type": "tool", "id": "c1", "name": "read", "state": {"status": "error", "input": {"filePath": "x"},
                "error": {"type": "tool.execution", "message": "File not found: x"}}, "time": {"created": 5}}
        c.execute("insert into session_message values('msg_a','s','assistant',0,5,5,?)",
                  (json.dumps({"agent": "build", "model": {"providerID": "p", "id": "m"}, "content": [tool], "time": {"created": 5}}),))
        streaming = {"type": "tool", "id": "c2", "name": "shell", "state": {"status": "streaming", "input": "{\"comm"},
                     "time": {"created": 6}}
        c.execute("insert into session_message values('msg_b','s','assistant',1,6,6,?)",
                  (json.dumps({"agent": "build", "model": {"providerID": "p", "id": "m"}, "content": [], "time": {"created": 6}}),))
        c.execute("insert into session_part values('msg_b','s',0,'tool','c2',6,6,?)", (json.dumps(streaming),))
        oc_schema.adapt(c)
        rows = c.execute("select id, json_extract(data,'$.tool'), json_extract(data,'$.state.status'), "
                         "json_extract(data,'$.state.error'), json_extract(data,'$.state.input') from part order by id").fetchall()
        self.assertEqual([r[1:] for r in rows], [("read", "error", "File not found: x", '{"filePath":"x"}'),
                                                 ("shell", "pending", None, "{}")])
        self.assertEqual(rows, sorted(rows))   # ids grow with time, as the incremental scans need
        self.assertTrue(rows[0][0] < rows[1][0])

    def test_nothing_written(self):
        """The views are temporary: opencode.db is opened read-only and not changed."""
        path, c = database("ro.db", v2=True)
        c.commit()
        c.close()
        before = (os.path.getsize(path), os.path.getmtime(path))
        ro = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
        self.assertEqual(oc_schema.adapt(ro), "v2")
        ro.execute("select count(*) from part").fetchone()
        ro.close()
        self.assertEqual((os.path.getsize(path), os.path.getmtime(path)), before)
        self.assertNotIn("message", {n for (n,) in sqlite3.connect(path).execute("select name from sqlite_master")})


class Catalog(unittest.TestCase):
    def test_v3_price_in_v1_shape(self):
        cost = {"text": {"input": {"price": 5, "cache": {"read": 0.5, "write": {"5m": 6.25, "1h": 10}}},
                         "output": {"price": 25}}, "web_search": {"price": 10}}
        self.assertEqual(catalog.normalize_cost(cost), {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 6.25})
        self.assertEqual(catalog.normalize_cost({"text": {"input": {"price": 1, "cache": {"explicit": {"write": 2}}},
                                                          "output": {"price": 3}}}),
                         {"input": 1, "output": 3, "cache_write": 2})
        old = {"input": 3, "output": 15, "cache_read": 0.3}
        self.assertEqual(catalog.normalize_cost(old), old)

    def test_catalog_from_database(self):
        path, c = database("catalog.db", v2=True)
        body = {"anthropic": {"id": "anthropic", "models": {"m": {"limit": {"context": 1000}, "cost": {
            "text": {"input": {"price": 2}, "output": {"price": 4}}}}}}}
        c.execute("insert into kv values('models-dev:v3:catalog',?,1,1)", (json.dumps({"updatedAt": 1, "digest": "d", "body": json.dumps(body)}),))
        c.commit()
        c.close()
        catalog.MODELS, catalog.DB = os.path.join(helpers.tmpdir(), "no-models.json"), path
        catalog.reset()
        self.assertEqual(catalog.load(), {"anthropic": {"models": {"m": {"limit": {"context": 1000}, "cost": {"input": 2, "output": 4}}}}})
        self.assertEqual(catalog.source(), "opencode.db")


if __name__ == "__main__":
    unittest.main()
