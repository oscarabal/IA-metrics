"""OpenCode collector against the fixture database."""
import os
import sqlite3
import sys
import json
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("opencode")
import fixtures  # noqa: E402

PATHS = fixtures.make_opencode(helpers.tmpdir())
os.environ.update(OPENCODE_DB=PATHS["db"], OPENCODE_MODELS=PATHS["models"], OPENCODE_COMMANDS_DIR=PATHS["commands"],
                  OPENCODE_QUOTA_DIR=PATHS["quota"], TZ_NAME="Europe/Madrid")
import exporter  # noqa: E402
from coach import index as coach_index, metrics as coach_metrics  # noqa: E402
import legacy_oracle  # noqa: E402


def warm():
    """What the background thread does before the first scrape."""
    exporter.refresh_skill_calls()
    c = exporter.connect()
    try:
        coach_index.INDEX.refresh(c)
        coach_metrics.refresh(c, exporter, force=True)
    finally:
        c.close()
    exporter.refresh_series()


class OpenCodeCollector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warm()
        cls.series = helpers.parse_metrics(exporter.collect())
        cls.legacy = helpers.parse_metrics(legacy_oracle.opencode_series(exporter))  # see legacy_oracle
        cls.srv = helpers.Server(exporter.Handler)
        cls.exp = fixtures.oc_expected()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    # -------------------------------------------------- Prometheus series and the legacy oracle
    def test_totals(self):
        s = self.series
        self.assertAlmostEqual(helpers.total(s, "opencode_cost_usd_total"), self.exp["cost"], places=6)
        self.assertEqual(helpers.total(s, "opencode_messages_total"), self.exp["messages"])
        self.assertEqual(helpers.total(s, "opencode_tokens_total"), self.exp["tokens"])

    def test_day_series_match_totals(self):
        s = self.legacy
        self.assertAlmostEqual(helpers.total(s, "opencode_day_cost_usd"), self.exp["cost"], places=6)
        self.assertEqual(helpers.total(s, "opencode_day_sessions"), self.exp["main_sessions"])

    def test_tools_skills_commands(self):
        s = self.legacy
        self.assertEqual(helpers.total(s, "opencode_day_tool_calls"), 6)       # read, edit, skill, grep, bash, read
        self.assertEqual(helpers.total(s, "opencode_day_tool_errors"), 1)      # the edit
        self.assertEqual(helpers.total(s, "opencode_day_skill_activations", kind="skill", skill="pdf"), 1)
        self.assertEqual(helpers.total(s, "opencode_day_skill_activations", kind="command", skill="revisa"), 1)
        self.assertEqual(helpers.total(s, "opencode_day_compactions"), 1)
        self.assertEqual(helpers.total(s, "opencode_day_aborted"), 1)

    # -------------------------------------------------- HTTP
    def test_pages(self):
        for path in ("/sessions", "/session/ses_aaa001", "/report", "/report.md", "/coach/summary", "/metrics"):
            status, _ = self.srv.get(path)
            self.assertEqual(status, 200, path)

    def test_unknown_host_rejected(self):
        self.assertEqual(self.srv.get("/sessions", host="evil.example.com")[0], 421)
        self.assertEqual(self.srv.get("/sessions", host=False)[0], 421)
        self.assertEqual(self.srv.get("/metrics", host="opencode-collector:9101")[0], 200)

    # -------------------------------------------------- /data API: equivalence with the legacy series (ADR 0002)
    def api(self, dataset, **params):
        return self.srv.json("/data/%s?%s" % (dataset, urllib.parse.urlencode(params)))

    def assertSame(self, legacy, labels, dataset, group, measure, legacy_filter=None, api_filter=None, rename=None):
        """Sum of a legacy series by `labels` == the API grouped by `group` (UTC days), key by key."""
        os.environ["TZ"] = "UTC"
        want = {}
        for n, lab, v in self.legacy:
            if n == legacy and all(lab.get(k) == w for k, w in (legacy_filter or {}).items()):
                key = tuple(lab[l] for l in labels)
                want[key] = want.get(key, 0) + v
        params = {"group": ",".join(group)}
        params.update({"f." + k: v for k, v in (api_filter or {}).items()})
        got = {}
        for r in self.api(dataset, **params):
            if r[measure]:
                got[tuple(str(r[g]) for g in group)] = r[measure]
        want = {k: v for k, v in want.items() if v}
        self.assertEqual(sorted(want), sorted(got), legacy)
        for k in want:
            self.assertAlmostEqual(want[k], got[k], places=6, msg="%s %s" % (legacy, k))

    def test_api_usage_equivalent(self):
        lab = ("day", "provider", "model", "agent", "project")
        self.assertSame("opencode_day_cost_usd", lab, "usage", lab, "cost")
        self.assertSame("opencode_day_messages", lab, "usage", lab, "messages")
        for t in ("input", "output", "reasoning", "cache_read", "cache_write"):
            self.assertSame("opencode_day_tokens", lab, "usage", lab, t, legacy_filter={"type": t})

    def test_api_sessions_equivalent(self):
        self.assertSame("opencode_day_sessions", ("day", "project"), "sessions", ("day", "project"), "sessions")

    def test_api_tools_equivalent(self):
        self.assertSame("opencode_day_tool_calls", ("day", "tool", "model", "project"), "tools", ("day", "tool", "model", "project"), "calls")
        self.assertSame("opencode_day_tool_errors", ("day", "tool", "error_class", "model", "project"), "tools",
                        ("day", "tool", "error_class", "model", "project"), "errors")
        self.assertSame("opencode_weekly_tool_calls", ("week", "tool", "project"), "tools", ("week", "tool", "project"), "calls")

    def test_api_compactions_and_aborts_equivalent(self):
        self.assertSame("opencode_day_compactions", ("day", "project"), "compactions", ("day", "project"), "compactions")
        self.assertSame("opencode_day_aborted", ("day", "agent", "project"), "usage", ("day", "agent", "project"), "aborted")

    def test_api_skills_equivalent(self):
        self.assertSame("opencode_day_skill_activations", ("day", "kind", "skill", "project", "result"), "skills",
                        ("day", "kind", "skill", "project", "result"), "activations")
        self.assertSame("opencode_day_skill_cost_usd", ("day", "kind", "skill", "project"), "skills",
                        ("day", "kind", "skill", "project"), "cost")
        detail = ("day", "kind", "skill", "project", "provider", "model", "agent")
        self.assertSame("opencode_day_skill_detail_cost_usd", detail, "skills", detail, "cost")
        self.assertSame("opencode_day_skill_detail_activations", detail + ("result",), "skills", detail + ("result",), "activations")

    def test_api_weekly_equivalent(self):
        self.assertSame("opencode_weekly_cost_usd", ("week", "project"), "usage", ("week", "project"), "cost")
        self.assertSame("opencode_weekly_agent_cost_usd", ("week", "agent", "project"), "usage", ("week", "agent", "project"), "cost")
        self.assertSame("opencode_weekly_agent_messages", ("week", "agent", "project"), "usage", ("week", "agent", "project"), "messages")

    def test_api_local_time_zone(self):
        """The night session (23:32 UTC on the 18th) belongs to the 19th in Madrid."""
        os.environ["TZ"] = "Europe/Madrid"
        days = {r["day"]: r["cost"] for r in self.api("usage", group="day")}
        self.assertAlmostEqual(days["2026-11-19"], 0.80 + 0.20, places=6)
        os.environ["TZ"] = "UTC"
        days = {r["day"]: r["cost"] for r in self.api("usage", group="day")}
        self.assertAlmostEqual(days["2026-11-18"], 0.10 + 0.05 + 0.01 + 0.20, places=6)

    def test_api_time_range_and_totals(self):
        t = self.api("usage")[0]
        self.assertAlmostEqual(t["cost"], self.exp["cost"], places=6)
        self.assertEqual(t["tokens"], self.exp["tokens"])
        t = self.api("usage", **{"from": fixtures.T0 + fixtures.D, "to": fixtures.T0 + 2 * fixtures.D - 1})
        self.assertAlmostEqual(t[0]["cost"], 0.80, places=6)
        self.assertEqual(self.api("usage/values", field="project"), [{"value": "api"}, {"value": "demo"}])

    def test_avoidable_errors_and_skill_results(self):
        t = self.api("tools")[0]
        self.assertEqual((t["calls"], t["errors"], t["avoidable_errors"]), (6, 1, 1))
        sk = {r["skill"]: r for r in self.api("skills", group="skill")}
        self.assertEqual((sk["pdf"]["ok"], sk["pdf"]["failed"]), (1, 0))
        self.assertAlmostEqual(sk["pdf"]["cost"], 0.10 + 0.05, places=6)   # its whole turn (msg_0002 + msg_0003)
        self.assertAlmostEqual(sk["revisa"]["cost"], 0.80, places=6)        # the command's turn

    def test_pages_accept_grafana_range(self):
        status, body = self.srv.get("/sessions?from=%d&to=%d" % (fixtures.T0 + fixtures.D, fixtures.T0 + 2 * fixtures.D))
        self.assertEqual(status, 200)
        self.assertIn("ses_bbb001", body)
        self.assertNotIn("ses_aaa001", body)
        self.assertEqual(self.srv.get("/coach/summary?from=%d&to=%d" % (fixtures.T0, fixtures.T0 + 3 * fixtures.D))[0], 200)

    def test_dashboard_queries_answered(self):
        """Every Infinity query of the OpenCode dashboard returns the fields its panel uses."""
        os.environ["TZ"] = "Europe/Madrid"
        queries = []
        for rel in (("opencode", "opencode.json"), ("global", "ia-overview.json")):
            path = os.path.join(helpers.ROOT, "grafana", "dashboards", *rel)
            queries += helpers.dashboard_queries(path, "http://opencode-collector:9101", fixtures.T0 - fixtures.D, fixtures.T0 + 4 * fixtures.D)
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
                by_panel.setdefault(title, set()).update(used)  # the coach endpoints: checked by their own tests
        for title, local, used in queries:
            missing = used - by_panel[title]
            self.assertFalse(missing, "%s: la API no devuelve %s" % (title, sorted(missing)))

    def test_prompts(self):
        rows = self.api("prompts", group="prompt_id,prompt,subagent", mask="none")
        by = {r["prompt_id"]: r for r in rows}
        self.assertEqual(by["msg_0001"]["prompt"], "arregla el login")
        self.assertEqual(by["msg_0006"]["prompt"], "/revisa")                  # a command, not its expanded template
        self.assertEqual(by["msg_0011"]["prompt"], "revisa los tests")         # the synthetic part is skipped
        self.assertEqual(by["msg_0004"]["subagent"], "sí")
        self.assertAlmostEqual(by["msg_0006"]["cost"], 0.80, places=9)
        self.assertAlmostEqual(sum(r["cost"] for r in rows), self.exp["cost"], places=6)   # every answer has its prompt

    def test_prompts_masked(self):
        status, body = self.srv.get("/data/prompts?group=prompt&mask=prompt")
        self.assertEqual(status, 200)
        for text in ("arregla", "revisa", "/revisa"):
            self.assertNotIn(text, body)

    def test_models_without_price(self):
        """Cost 0 with tokens is valued at API price; only a model without any price is flagged."""
        self.assertEqual(exporter.prices_status(), "OK\n")
        self.assertFalse([n for n, _l, _v in self.series if n == "opencode_model_without_price_messages"])
        extra = [("msg_x1", "miprov", "mi-modelo"), ("msg_x2", "opencode", "big-pickle"), ("msg_x3", "lmstudio", "qwen"),
                 ("msg_x4", "github-copilot", "claude-sonnet-4.5")]
        db = sqlite3.connect(PATHS["db"])
        for mid, prov, model in extra:
            d = {"role": "assistant", "agent": "build", "providerID": prov, "modelID": model, "cost": 0,
                 "tokens": {"input": 100, "output": 10, "reasoning": 0, "cache": {"read": 0, "write": 0}}}
            db.execute("insert into message values(?,?,?,?,?)", (mid, "ses_aaa001", fixtures.T0, fixtures.T0, json.dumps(d)))
        db.commit()
        try:
            exporter.refresh_series()   # what the background thread does every SERIES_EVERY seconds
            found = [(lab, v) for n, lab, v in helpers.parse_metrics(exporter.collect()) if n == "opencode_model_without_price_messages"]
            self.assertEqual(len(found), 1)
            self.assertIn("miprov/mi-modelo", str(found))
            status, body = self.srv.get("/prices/missing")
            self.assertEqual(status, 200)
            self.assertTrue(body.startswith("SIN PRECIO"), body)
            self.assertIn("miprov/mi-modelo: 1 mensajes", body)
            for other in ("big-pickle", "qwen", "github-copilot"):
                self.assertNotIn(other, body)
            rows = {(r[0], r[1]): r for r in exporter.model_costs(exporter.connect())}
            copilot = rows[("github-copilot", "claude-sonnet-4.5")]
            self.assertEqual(copilot[10], "anthropic")                      # Copilot gives no price: the maker's
            self.assertAlmostEqual(copilot[11], (100 * 3 + 10 * 15) / 1e6)  # tokens × anthropic's price
            self.assertEqual(rows[("lmstudio", "qwen")][11], 0)
            status, page = self.srv.get("/prices")
            self.assertEqual(status, 200)
            for word in ("SIN PRECIO", "calculado", "gratis", "local", "1 modelos sin precio</b>"):
                self.assertIn(word, page)
            self.assertEqual(page.count('<tr class="flag">'), 1)
            self.assertEqual(self.srv.get("/prices", host="evil.example.com")[0], 421)
        finally:
            db.execute("delete from message where id like 'msg_x%'")
            db.commit()
            db.close()
        self.assertEqual(exporter.prices_status(), "OK\n")

    def test_api_cost_of_zero_cost_messages(self):
        """The /data API values a message stored with cost 0 at API price (cost_source computed)."""
        from types import SimpleNamespace as M
        import api_prices
        m = M(cost=0, provider="github-copilot", model="claude-opus-4.1", inp=1000, out=100, reasoning=0, cache_read=0, cache_write=0)
        cost, source = api_prices.hybrid(m)
        self.assertEqual(source, "computed")
        self.assertAlmostEqual(cost, (1000 * 15 + 100 * 75) / 1e6)
        self.assertEqual(api_prices.hybrid(M(cost=0.5, provider="x", model="y", inp=1, out=1, reasoning=0, cache_read=0, cache_write=0)), (0.5, "tool"))
        self.assertEqual(api_prices.hybrid(M(cost=0, provider="x", model="y", inp=1, out=1, reasoning=0, cache_read=0, cache_write=0)), (0.0, "missing"))
        self.assertEqual(api_prices.hybrid(M(cost=0, provider="x", model="y", inp=0, out=0, reasoning=0, cache_read=0, cache_write=0)), (0.0, "tool"))
        rows = self.api("usage", group="cost_source") if hasattr(self, "api") else None
        if rows is not None:
            self.assertEqual({r["cost_source"] for r in rows}, {"tool"})   # every fixture message has its cost

    def test_health(self):
        status, body = self.srv.get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith("ok"), body)
        self.assertEqual(self.srv.get("/health", host="evil.example.com")[0], 421)
        self.assertEqual(self.srv.get("/health", host="127.0.0.1:9100")[0], 200)   # what the healthcheck sends

    def test_source_freshness(self):
        """«Estado de las fuentes»: newest message of opencode.db and when the background thread read it."""
        newest = max(m[2] for m in fixtures.OC_MESSAGES)
        self.assertEqual(helpers.total(self.series, "opencode_last_message_timestamp_seconds"), newest // 1000)
        self.assertGreater(helpers.total(self.series, "opencode_db_read_timestamp_seconds"), fixtures.T0 / 1000)

    def test_no_legacy_series(self):
        """The per-day and per-week series are gone from the scrape (ADR 0002): only /data has them."""
        names = {n for n, _l, _v in self.series}
        self.assertFalse([n for n in names if n.startswith(("opencode_day_", "opencode_weekly_", "opencode_skill_scan"))])
        self.assertIn("opencode_cost_usd_total", names)
        self.assertIn("opencode_context_tokens", names)

    def test_scrape_reads_no_database(self):
        """A scrape serves what the background thread computed: it must not open opencode.db."""
        real = exporter.connect
        exporter.connect = lambda: (_ for _ in ()).throw(AssertionError("scrape opened the database"))
        try:
            names = {n for n, _l, _v in helpers.parse_metrics(exporter.collect())}
        finally:
            exporter.connect = real
        self.assertIn("opencode_cost_usd_total", names)

    def test_report_json_contract(self):
        r = self.srv.json("/report.json")
        for key in ("format_version", "summary", "findings"):
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
