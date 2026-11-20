"""Claude Code collector against the fixture conversations and a fake Loki."""
import os
import sys
import json
import sqlite3
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("claude")
import fixtures  # noqa: E402
import fake_loki  # noqa: E402

TMP = helpers.tmpdir()
PATHS = fixtures.make_claude(os.path.join(TMP, "claude"))
os.environ.update(PROJECTS_DIR=PATHS["projects"], CLAUDE_COMMANDS_DIR=PATHS["commands"], CLAUDE_SKILLS_DIR=PATHS["skills"],
                  COACH_DB=os.path.join(TMP, "coach.db"), LOKI_URL=fake_loki.start(), TZ_NAME="Europe/Madrid")
import index  # noqa: E402
import map as collector  # noqa: E402
import pricing  # noqa: E402
import ledger_source  # noqa: E402
from coach import metrics as coach_metrics  # noqa: E402


def warm():
    """What the background threads do before the first scrape."""
    index.INDEX.scan_files()
    index.INDEX.scan_costs()
    index.INDEX.scan_tool_events()
    coach_metrics._round(index.INDEX)


class ClaudeCollector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warm()
        cls.series = helpers.parse_metrics(collector.collect())
        cls.srv = helpers.Server(collector.Handler)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_sessions_and_projects(self):
        s = self.series
        projects = {lab["project"] for n, lab, _v in s if n == "claude_session_project"}
        self.assertEqual(projects, {"demo", "api"})

    def test_costs_from_telemetry(self):
        ix = index.INDEX
        self.assertEqual(ix.costs, fixtures.CC_TELEMETRY_COST)

    def test_coach_series(self):
        s = self.series
        self.assertEqual(helpers.total(s, "claude_coach_day_tool_errors"), 1)
        self.assertEqual(helpers.total(s, "claude_coach_day_compactions"), 1)
        self.assertGreaterEqual(helpers.total(s, "claude_day_skill_uses"), 1)

    def test_pages(self):
        for path in ("/sessions", "/session/0f8fad5b-d9cb-469f-a165-70867728950e", "/report", "/report.md", "/coach/summary", "/metrics"):
            status, _ = self.srv.get(path)
            self.assertEqual(status, 200, path)

    def test_unknown_host_rejected(self):
        self.assertEqual(self.srv.get("/sessions", host="evil.example.com")[0], 421)
        self.assertEqual(self.srv.get("/metrics", host="claude-collector:9100")[0], 200)

    # -------------------------------------------------- /data API (ADR 0002)
    def api(self, dataset, **params):
        return self.srv.json("/data/%s?%s" % (dataset, urllib.parse.urlencode(params)))

    def assertSame(self, legacy, labels, dataset, group, measure, legacy_filter=None, api_filter=None):
        os.environ["TZ"] = "UTC"
        want = {}
        for n, lab, v in self.series:
            if n == legacy and all(lab.get(k) == w for k, w in (legacy_filter or {}).items()):
                key = tuple(lab[l] for l in labels)
                want[key] = want.get(key, 0) + v
        params = {"group": ",".join(group)}
        params.update({"f." + k: v for k, v in (api_filter or {}).items()})
        got = {tuple(str(r[g]) for g in group): r[measure] for r in self.api(dataset, **params) if r[measure]}
        want = {k: v for k, v in want.items() if v}
        self.assertEqual(sorted(want), sorted(got), legacy)
        for k in want:
            self.assertAlmostEqual(want[k], got[k], places=6, msg="%s %s" % (legacy, k))

    def test_hybrid_cost(self):
        rows = {r["cost_source"]: r for r in self.api("usage", group="cost_source")}
        self.assertAlmostEqual(rows["telemetry"]["cost"], sum(fixtures.CC_TELEMETRY_COST.values()), places=9)
        haiku = pricing.cost("claude-haiku-4-5", fixtures.T0, 20, 80, 0, 0)      # req_004: no telemetry event
        self.assertAlmostEqual(rows["computed"]["cost"], haiku, places=12)
        self.assertNotIn("missing", rows)
        self.assertEqual(rows["telemetry"]["telemetry"], 3)

    def test_cost_diagnostic(self):
        """For the requests the telemetry reported, both figures are there to compare."""
        r = self.api("usage", **{"f.cost_source": "telemetry", "group": "model", "measures": "cost_telemetry,cost_computed"})
        by = {x["model"]: x for x in r}
        self.assertAlmostEqual(by["claude-sonnet-4-5"]["cost_telemetry"], 0.021 + 0.012, places=9)
        want = pricing.cost("claude-sonnet-4-5", fixtures.T0, 100, 200, 5000, 300) + pricing.cost("claude-sonnet-4-5", fixtures.T0, 50, 100, 6000, 0)
        self.assertAlmostEqual(by["claude-sonnet-4-5"]["cost_computed"], want, places=9)

    def test_pages_use_hybrid_cost(self):
        status, body = self.srv.get("/session/7c9e6679-7425-40de-944b-e07fc1f90ae7")
        self.assertEqual(status, 200)
        self.assertIn("2 de 2 mensajes con coste", body)

    def test_api_sessions_equivalent(self):
        self.assertSame("claude_day_sessions", ("day", "project"), "sessions", ("day", "project"), "sessions")

    def test_api_tools_equivalent(self):
        self.assertSame("claude_coach_day_tool_calls", ("day", "tool", "model", "project"), "tools", ("day", "tool", "model", "project"), "calls")
        self.assertSame("claude_coach_day_tool_errors", ("day", "tool", "error_class", "model", "project"), "tools",
                        ("day", "tool", "error_class", "model", "project"), "errors")
        self.assertSame("claude_coach_week_tool_calls", ("week", "tool", "project"), "tools", ("week", "tool", "project"), "calls")

    def test_api_compactions_interrupts_skills_equivalent(self):
        self.assertSame("claude_coach_day_compactions", ("day", "project"), "compactions", ("day", "project"), "compactions")
        self.assertSame("claude_day_skill_uses", ("day", "skill", "project", "kind"), "skills", ("day", "skill", "project", "kind"), "activations")

    def test_api_command_cost_equivalent_on_telemetry(self):
        """Where the telemetry knows the cost, the command cost is the same as the legacy series."""
        self.assertSame("claude_day_command_cost_usd", ("day", "command", "project", "model", "origin"), "commands",
                        ("day", "command", "project", "model", "origin"), "cost", api_filter={"cost_source": "telemetry"})
        self.assertTrue(any(lab.get("command") == "revisa" for n, lab, _v in self.series if n == "claude_day_command_cost_usd"))

    def test_api_weekly_equivalent(self):
        self.assertSame("claude_coach_week_cost_usd", ("week", "model", "project"), "usage", ("week", "model", "project"), "cost")
        self.assertSame("claude_coach_week_messages", ("week", "model", "project"), "usage", ("week", "model", "project"), "messages")

    def test_api_distinct_sessions(self):
        self.assertEqual(self.api("usage", distinct="session")[0]["distinct_session"], 2)

    def test_dashboard_queries_answered(self):
        """Every Infinity query of the Claude Code dashboard returns the fields its panel uses."""
        os.environ["TZ"] = "Europe/Madrid"
        queries = []
        for rel in (("claude", "claude-code.json"), ("global", "ia-overview.json")):
            path = os.path.join(helpers.ROOT, "grafana", "dashboards", *rel)
            queries += helpers.dashboard_queries(path, "http://claude-collector:9100", fixtures.T0 - fixtures.D, fixtures.T0 + 4 * fixtures.D)
        self.assertGreaterEqual(len(queries), 27)
        by_panel = {}
        for title, local, used in queries:
            status, body = self.srv.get(local)
            self.assertEqual(status, 200, "%s: %s -> %s" % (title, local, body[:300]))
            if local.startswith("/data/"):
                rows = json.loads(body)
                self.assertTrue(rows, "%s: sin filas (%s)" % (title, local))
                by_panel.setdefault(title, set()).update(*[set(r) for r in rows])
            else:
                by_panel.setdefault(title, set()).update(used)
        for title, local, used in queries:
            missing = used - by_panel[title]
            self.assertFalse(missing, "%s: la API no devuelve %s" % (title, sorted(missing)))

    def test_usage_survives_deleted_conversations(self):
        """Claude Code deletes old conversation files (cleanupPeriodDays): their usage must stay (ADR 0002)."""
        import shutil
        from coach import store as coach_store
        root = os.path.join(helpers.tmpdir(), "projects")
        shutil.copytree(PATHS["projects"], root)
        db = os.path.join(helpers.tmpdir(), "coach.db")
        saved_root = index.ROOT
        try:
            index.ROOT = root

            def run(deleted=()):
                """A collector start: restore what is stored, read the files, store what changed."""
                ix, st = index.Index(), coach_store.Store(db)
                st.restore(ix)
                restored = st.restore_sessions(ix, root)
                ix.scan_files()
                st.archive_sessions(ix)
                with ix.lock:
                    usage = {sid: (len(x["msgs"]), sum(m[3] for m in x["msgs"].values()), len(x["compactions"]), len(x["skills"]))
                             for sid, x in ix.sessions.items()}
                return usage, restored, ix

            first, restored, _ix = run()
            self.assertEqual(restored, 0)
            gone = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
            folder = fixtures.CC_SESSIONS[gone][0]
            os.remove(os.path.join(root, folder, gone + ".jsonl"))
            shutil.rmtree(os.path.join(root, folder, gone))       # its subagents go too
            second, restored, ix = run()
            self.assertEqual(restored, 1)
            self.assertEqual(second, first)                        # same messages, tokens, compactions, skills
            self.assertEqual(ix.sessions[gone]["project"], "api")
            self.assertEqual(ix.sessions[gone]["title"], "")       # titles and paths are never archived
            third, restored, _ix = run()                           # a later restart: still there, nothing doubled
            self.assertEqual(third, first)
            with sqlite3.connect(db) as c:
                blob = " ".join(r[0] for r in c.execute("select data from session_archive"))
            for private in ("Sesión", "C:\\\\Workspace", "haz la tarea", "String to replace"):
                self.assertNotIn(private, blob)
        finally:
            index.ROOT = saved_root

    def test_tools_bytes_and_duration_from_conversations(self):
        """What the «Herramientas» panel needed Loki for now comes from the conversation files."""
        by = {r["tool"]: r for r in self.api("tools", group="tool")}
        self.assertEqual(by["Read"]["bytes"], len("x"))
        self.assertEqual(by["Edit"]["bytes"], len("String to replace not found in file.".encode()))
        self.assertEqual((by["Read"]["duration_ms"], by["Read"]["timed"]), (500, 1))   # result 500 ms after the call
        self.assertEqual(by["Skill"]["calls"] if "Skill" in by else 0, 0)              # no result yet: not finished

    def test_tool_result_extras(self):
        """toolUseResult.durationMs and persistedOutputSize, when Claude Code writes them, win over estimates."""
        ix = index.Index()
        s = index.new_session("s", "p")
        call = '{"type":"assistant","timestamp":"2026-11-18T10:00:00.000Z","message":{"id":"m1","model":"claude-sonnet-4-5","content":[{"type":"tool_use","id":"tu1","name":"Bash","input":{}}],"usage":{"input_tokens":1,"output_tokens":1}}}'
        result = ('{"type":"user","timestamp":"2026-11-18T10:00:09.000Z","toolUseResult":{"durationMs":1234,"persistedOutputSize":900000},'
                  '"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":"preview"}]}}')
        ix._line(s, call, False, "")
        ix._line(s, result, False, "")
        c = s["calls"]["tu1"]
        self.assertEqual((c[8], c[9]), (900000, 1234))

    def test_prompt_cost(self):
        rows = self.api("prompts", group="prompt_id,session,prompt", sort="-cost")
        top = rows[0]
        self.assertEqual(top["session"], "7c9e6679-7425-40de-944b-e07fc1f90ae7")
        self.assertAlmostEqual(top["cost"], fixtures.CC_TELEMETRY_COST["req_003"], places=9)
        total = sum(r["cost"] for r in rows)
        self.assertAlmostEqual(total, self.api("usage")[0]["cost"] - self.api("usage", **{"f.subagent": "sí"})[0]["cost"], places=9)

    def test_prompt_text_opt_in_never_archived(self):
        import shutil
        from coach import store as coach_store
        root = os.path.join(helpers.tmpdir(), "projects")
        shutil.copytree(PATHS["projects"], root)
        saved = index.ROOT, index.PROMPT_TEXT
        try:
            index.ROOT, index.PROMPT_TEXT = root, True
            ix = index.Index()
            ix.scan_files()
            texts = {t for x in ix.sessions.values() for t in x["prompts"].values()}
            self.assertIn("haz la tarea 0", texts)
            db = os.path.join(helpers.tmpdir(), "coach.db")
            coach_store.Store(db).archive_sessions(ix)
            with sqlite3.connect(db) as c:
                blob = " ".join(r[0] for r in c.execute("select data from session_archive"))
            self.assertNotIn("haz la tarea", blob)
        finally:
            index.ROOT, index.PROMPT_TEXT = saved

    def test_effort_from_conversations(self):
        """req_004 had no telemetry: its effort comes from the conversation file."""
        by = {r["effort"]: r for r in self.api("usage", group="effort")}
        self.assertEqual(set(by), {"high", "medium"})

    def test_report_without_telemetry_uses_conversations(self):
        """Effort, tool bytes and permission decisions reach the report for what the telemetry missed."""
        from coach import report as coach_report
        _sessions, _costs, tel = coach_report.snapshot(index.INDEX)
        efforts = {(m, e) for _ts, _sid, m, e, _src, _c, _o in tel["requests"]}
        self.assertIn(("claude-haiku-4-5", "medium"), efforts)                    # only in the conversation
        self.assertEqual(len(tel["requests"]), len(fixtures.CC_ASSISTANT))          # 3 from telemetry + 1, no duplicates
        decisions = [t for t in tel["tools"] if t[0] == "decision"]
        self.assertEqual([(t[3], t[5], t[6]) for t in decisions], [("Edit", "accept", "user_temporary")])
        results = {t[3]: t[4] for t in tel["tools"] if t[0] == "result"}
        self.assertEqual(results["Read"], 1)

    def test_prompt_opening(self):
        self.assertEqual(index.prompt_opening("<command-message>revisa</command-message>\n<command-name>/revisa</command-name>\n"
                                              "<command-args>pagos.py  rápido</command-args>"), "/revisa pagos.py rápido")
        self.assertEqual(index.prompt_opening("<command-name>/clear</command-name>"), "/clear")
        self.assertEqual(index.prompt_opening("  arregla\n el   login "), "arregla el login")
        self.assertEqual(len(index.prompt_opening("x" * 1000)), index.PROMPT_TEXT_CHARS)

    def test_prompt_text_on_and_masked_by_the_dashboard(self):
        self.assertTrue(index.PROMPT_TEXT)
        shown = {r["prompt"] for r in self.api("prompts", group="prompt", mask="none")}
        self.assertIn("haz la tarea 0", shown)
        self.assertIn("/revisa", shown)                       # the command turn, without Claude Code's tags
        hidden = {r["prompt"] for r in self.api("prompts", group="prompt", mask="prompt")}
        self.assertFalse({t for t in hidden if t.strip("*")}, hidden)
        status, body = self.srv.get("/data/prompts?group=prompt&mask=prompt")
        self.assertNotIn("haz la tarea", body)                # not even in the raw answer

    def test_hourly_in_local_time(self):
        os.environ["TZ"] = "Europe/Madrid"
        hours = {r["hour"]: r["tokens"] for r in self.api("usage", group="hour")}
        self.assertIn("2026-11-19 00:00", hours)   # 23:32 UTC on the 18th
        os.environ["TZ"] = "UTC"
        self.assertIn("2026-11-18 23:00", {r["hour"] for r in self.api("usage", group="hour")})

    def test_models_without_price(self):
        """Every fixture model has a price; a new one shows up in the metric, /prices/missing and the log."""
        self.assertEqual(collector.prices_status(), "OK\n")
        self.assertFalse([n for n, _l, _v in self.series if n == "claude_model_without_price_messages"])
        self.assertEqual(index.INDEX.progress[0], index.INDEX.progress[1])
        index.INDEX.done = False
        try:
            self.assertTrue(collector.prices_status().startswith("PENDIENTE: leyendo"))
        finally:
            index.INDEX.done = True
        s = next(iter(index.INDEX.sessions.values()))
        s["msgs"]["msg_sin_precio"] = [0, "claude-nuevo-9-20990101", 1, 1, 0, 0, False, "req_x", None, 0, None, None]
        try:
            series = helpers.parse_metrics(collector.collect())
            found = [(lab, v) for n, lab, v in series if n == "claude_model_without_price_messages"]
            self.assertEqual(len(found), 1)
            self.assertIn("claude-nuevo-9", str(found[0][0]))
            status, body = self.srv.get("/prices/missing")
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith("SIN PRECIO"), body)
            self.assertIn("claude-nuevo-9: 1 mensajes", body)
            status, page = self.srv.get("/prices")
            self.assertEqual(status, 200)
            self.assertIn("SIN PRECIO", page)
            self.assertIn("claude-nuevo-9", page)
            self.assertIn("Tabla de precios (prices.json)", page)
            for model in pricing.table()["models"]:
                self.assertIn(model, page)
            self.assertEqual(self.srv.get("/prices", host="evil.example.com")[0], 421)
        finally:
            del s["msgs"]["msg_sin_precio"]
        self.assertNotIn("modelos sin precio</b>", self.srv.get("/prices")[1])
        self.assertEqual(collector.prices_status(), "OK\n")

    def test_legacy_switch(self):
        collector.LEGACY_DAY_METRICS = False
        try:
            names = {n for n, _l, _v in helpers.parse_metrics(collector.collect())}
        finally:
            collector.LEGACY_DAY_METRICS = True
        self.assertFalse([n for n in names if n.startswith(("claude_day_", "claude_coach_day_", "claude_coach_week_"))])
        self.assertIn("claude_session_project", names)
        self.assertIn("claude_context_tokens", names)

    def test_report_json_contract(self):
        r = self.srv.json("/report.json")
        for key in ("format_version", "summary", "findings"):
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
