"""collectors/common: ledger query engine, time buckets and the Host check."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("common")
from common import coach_rules, html_page, ledger, markdown, security  # noqa: E402

H = 3600 * 1000
NIGHT = 1795044600000  # 2026-11-18T23:30:00Z = 2026-11-19 00:30 in Madrid
ROWS = [
    {"ts": NIGHT, "project": "api", "model": "opus", "cost": 0.5, "messages": 1},
    {"ts": NIGHT - 12 * H, "project": "demo", "model": "sonnet", "cost": 0.25, "messages": 1},
    {"ts": NIGHT - 11 * H, "project": "demo", "model": "sonnet", "cost": 0.25, "messages": 1},
]


def q(**kw):
    return {k.replace("__", "."): [str(v)] for k, v in kw.items()}


class SharedPieces(unittest.TestCase):
    def test_markdown_cells_stay_on_one_line(self):
        """Names read from conversations cannot add rows or text to the report pasted into an AI chat."""
        t = markdown.table(["skill"], [["a|b\n| injected | row |\r\x00"]])
        self.assertEqual(t.count("\n"), 2)                       # header, rule, one row
        self.assertIn("a\\|b", t)

    def test_html_escapes(self):
        self.assertEqual(html_page.e('<b a="1">'), "&lt;b a=&quot;1&quot;&gt;")
        self.assertEqual(html_page.when(0), "—")


class CoachRules(unittest.TestCase):
    def test_catalogue_keeps_shared_rules_first(self):
        r = coach_rules.rules("Coste por agente", D11="Variantes -fast")
        self.assertEqual(list(r)[:10], ["D%d" % i for i in range(1, 11)])
        self.assertEqual(r["D2"], "Coste por agente")
        self.assertEqual(list(r)[-1], "D11")

    def test_severity(self):
        s = {"cost_usd": 100.0}
        self.assertEqual(coach_rules.severity({"impact_usd": 10}, s), "alta")
        self.assertEqual(coach_rules.severity({"impact_usd": 2}, s), "media")
        self.assertEqual(coach_rules.severity({"impact_usd": 1}, s), "baja")
        self.assertEqual(coach_rules.severity({"impact_tokens": 60_000_000}, s), "media")
        self.assertEqual(coach_rules.severity({"impact_count": 100}, {"cost_usd": 0}), "alta")
        self.assertEqual(coach_rules.severity({"impact_count": 20}, {"cost_usd": 0}), "media")

    def test_finding_shape(self):
        f = coach_rules.finding("D1", "t", "e", "r", impact_usd=1.234567, sessions=range(9))
        self.assertEqual(f["impact_usd"], 1.2346)
        self.assertEqual(len(f["sessions"]), 5)

    def test_no_threshold_outside_coach_rules(self):
        """The rules D1–D10 of both collectors compare against coach_rules constants, never against a number
        written in the rule (0 and 1 are not thresholds; `len(x) < 2` is «fewer than two to compare»)."""
        import ast
        for tool in ("claude", "opencode"):
            path = os.path.join(helpers.COLLECTORS, tool, "coach", "report.py")
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for fn in tree.body:
                if not (isinstance(fn, ast.FunctionDef) and fn.name.split("_")[0] in {"d%d" % i for i in range(1, 11)}):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Compare):
                        continue
                    def numbers(n):  # the constants of an expression, without slice bounds (`name[3:]` is not a threshold)
                        if isinstance(n, ast.Slice):
                            return
                        yield n
                        for child in ast.iter_child_nodes(n):
                            yield from numbers(child)
                    for side in [node.left] + node.comparators:
                        for c in numbers(side):
                            if not (isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool)):
                                continue
                            if c.value in (0, 1):
                                continue
                            if c.value == 2 and isinstance(node.left, ast.Call) and getattr(node.left.func, "id", "") == "len":
                                continue
                            self.fail("%s/coach/report.py, %s, línea %d: umbral %r escrito en la regla; muévelo a common/coach_rules.py"
                                      % (tool, fn.name, node.lineno, c.value))


class Buckets(unittest.TestCase):
    def test_local_day_differs_from_utc(self):
        os.environ["TZ"] = "Europe/Madrid"
        self.assertEqual(ledger.bucket(NIGHT, "day")[0], "2026-11-19")
        os.environ["TZ"] = "UTC"
        self.assertEqual(ledger.bucket(NIGHT, "day")[0], "2026-11-18")

    def test_week_starts_monday(self):
        os.environ["TZ"] = "UTC"
        self.assertEqual(ledger.bucket(NIGHT, "week")[0], "2026-11-16")

    def test_dst_change_day(self):  # 2026-10-25 has 25 hours in Madrid
        os.environ["TZ"] = "Europe/Madrid"
        label, start = ledger.bucket(1792965600000, "day")  # 2026-10-25 22:00Z = 23:00 CET
        self.assertEqual(label, "2026-10-25")
        self.assertEqual(start, 1792879200000)  # 2026-10-24T22:00:00Z = 00:00 CEST


class AutoBuckets(unittest.TestCase):
    """group=auto: the bucket follows the range, and the first point never falls before it."""
    def setUp(self):
        os.environ["TZ"] = "Europe/Madrid"

    def test_step_follows_the_range(self):
        for span, label in ((15 * ledger.MINUTE, "1 min"), (6 * ledger.HOUR, "10 min"), (7 * ledger.DAY, "6 h"),
                            (30 * ledger.DAY, "día"), (120 * ledger.DAY, "semana"), (365 * ledger.DAY, "mes")):
            self.assertEqual(ledger.auto_step(0, span)[2], label, span)

    def test_short_range_stays_inside(self):
        """The case that left the charts empty with «last 15 minutes»: day and hour buckets start before it."""
        since = NIGHT - 15 * ledger.MINUTE
        rows = [{"ts": NIGHT - 5 * ledger.MINUTE, "project": "p", "cost": 0.5}, {"ts": NIGHT - 14 * ledger.MINUTE, "project": "p", "cost": 0.25}]
        out = ledger.query(rows, {"from": [str(since)], "to": [str(NIGHT)], "group": ["auto"], "measures": ["cost"]})
        self.assertEqual([r["cost"] for r in out], [0.25, 0.5])
        self.assertTrue(all(since <= r["time"] <= NIGHT for r in out), out)
        self.assertEqual({r["interval"] for r in out}, {"1 min"})
        day = ledger.query(rows, {"from": [str(since)], "to": [str(NIGHT)], "group": ["day"]})
        self.assertLess(day[0]["time"], since)   # why the old panels were empty

    def test_aligned_in_local_time(self):
        """6-hour buckets start at 00:00, 06:00... in Madrid, not in UTC."""
        step = ledger.auto_step(0, 7 * ledger.DAY)
        label, _start = ledger.auto_bucket(NIGHT, step)   # 23:30Z on the 18th = 00:30 on the 19th in Madrid
        self.assertEqual(label, "2026-11-19 00:00")

    def test_long_range_uses_calendar_buckets(self):
        out = ledger.query(ROWS, {"from": ["0"], "to": [str(NIGHT + ledger.DAY)], "group": ["auto"]})
        self.assertTrue(all(r["interval"] == "mes" and len(r["auto"]) == 7 for r in out), out)


class Query(unittest.TestCase):
    def setUp(self):
        os.environ["TZ"] = "Europe/Madrid"

    def test_totals(self):
        self.assertEqual(ledger.query(ROWS, {}), [{"cost": 1.0, "messages": 3, "n": 3}])

    def test_group_by_day_and_model(self):
        r = ledger.query(ROWS, q(group="day,model"))
        self.assertEqual([(x["day"], x["model"], x["cost"]) for x in r],
                         [("2026-11-18", "sonnet", 0.5), ("2026-11-19", "opus", 0.5)])
        self.assertIn("time", r[0])

    def test_time_range_and_project(self):
        self.assertEqual(ledger.query(ROWS, q(**{"from": NIGHT - 11 * H, "project": "demo,api"}))[0]["n"], 2)
        self.assertEqual(ledger.query(ROWS, q(project="All"))[0]["n"], 3)
        self.assertEqual(ledger.query(ROWS, q(project="api"))[0]["cost"], 0.5)

    def test_field_filter_sort_limit(self):
        r = ledger.query(ROWS, q(group="project", sort="-messages", limit=1))
        self.assertEqual(r, [{"project": "demo", "cost": 0.5, "messages": 2, "n": 2}])
        self.assertEqual(ledger.query(ROWS, q(f__model="opus"))[0]["n"], 1)

    def test_empty_range_gives_zeros(self):
        self.assertEqual(ledger.query(ROWS, q(**{"from": 1, "to": 2})), [{"cost": 0, "messages": 0, "n": 0}])

    def test_calc_and_totals(self):
        r = ledger.query(ROWS, q(group="model", calc="share:cost/total_cost;per_msg:cost/messages;bad:cost/0"))
        by = {x["model"]: x for x in r}
        self.assertEqual(by["sonnet"]["share"], 0.5)
        self.assertEqual(by["opus"]["per_msg"], 0.5)
        self.assertIsNone(by["opus"]["bad"])

    def test_calc_is_safe(self):
        for bad in ("__import__('os')", "cost.real", "cost if 1 else 0", "x:"):
            with self.assertRaises(ValueError):
                ledger.query(ROWS, q(calc="v:" + bad))

    def test_top_and_other(self):
        r = ledger.query(ROWS, q(group="project", top="project:1:messages", other="otros"))
        self.assertEqual({x["project"]: x["n"] for x in r}, {"demo": 2, "otros": 1})
        r = ledger.query(ROWS, q(group="project", top="project:1:messages"))
        self.assertEqual([x["project"] for x in r], ["demo"])

    def test_exclude_and_nonzero(self):
        self.assertEqual(ledger.query(ROWS, q(nf__model="opus"))[0]["n"], 2)
        rows = ROWS + [{"ts": NIGHT, "project": "x", "model": "m", "cost": 0.0, "messages": 0}]
        self.assertNotIn("x", [r["project"] for r in ledger.query(rows, q(group="project", nonzero="cost"))])

    def test_distinct(self):
        self.assertEqual(ledger.query(ROWS, q(distinct="project"))[0]["distinct_project"], 2)
        r = {x["model"]: x["distinct_project"] for x in ledger.query(ROWS, q(group="model", distinct="project"))}
        self.assertEqual(r, {"opus": 1, "sonnet": 1})

    def test_mask(self):
        rows = [dict(r, prompt=t) for r, t in zip(ROWS, ("arregla el login", "x" * 100, ""))]
        out = {r["model"] + str(i): r["prompt"] for i, r in enumerate(ledger.query(rows, q(group="model,prompt", mask="prompt")))}
        self.assertEqual(sorted(out.values()), ["", "*" * 16, "*" * 40])
        self.assertIn("x" * 100, {r["prompt"] for r in ledger.query(rows, q(group="prompt", mask="none"))})

    def test_queryparam_project(self):
        self.assertEqual(ledger.query(ROWS, {"var-project": ["api"]})[0]["n"], 1)
        self.assertEqual(ledger.query(ROWS, {"var-project": [".*"]})[0]["n"], 3)

    def test_queryparam_sessions(self):
        rows = [dict(r, session="s%d" % i) for i, r in enumerate(ROWS)]
        self.assertEqual(ledger.query(rows, {"var-sessions": ["s0", "s2"]})[0]["n"], 2)
        self.assertEqual(ledger.query(rows, {"var-sessions": [".*"]})[0]["n"], 3)

    def test_empty_dataset_is_not_an_error(self):
        self.assertEqual(ledger.query([], q(group="model,prompt", mask="prompt")), [])
        self.assertEqual(ledger.query([], q(measures="cost")), [{"cost": 0}])

    def test_unknown_group_is_an_error(self):
        with self.assertRaises(ValueError):
            ledger.query(ROWS, q(group="nope"))

    def test_handle(self):
        lg = ledger.Ledger()
        lg.register("usage", lambda: ROWS)
        self.assertEqual(lg.handle("/data", "")[1]["usage"]["dimensions"], ["model", "project"])
        self.assertEqual(lg.handle("/data/usage/values", "field=project")[1], [{"value": "api"}, {"value": "demo"}])
        self.assertEqual(lg.handle("/data/nope", "")[0], 404)
        self.assertEqual(lg.handle("/data/usage", "group=nope")[0], 400)


class Host(unittest.TestCase):
    def test_names(self):
        for h, ok in (("localhost:9100", True), ("127.0.0.1", True), ("[::1]:9101", True), ("claude-collector:9100", True),
                      ("evil.com", False), ("localhost.evil.com:9100", False), ("", False), (None, False)):
            self.assertEqual(security.host_allowed(h), ok, h)


if __name__ == "__main__":
    unittest.main()
