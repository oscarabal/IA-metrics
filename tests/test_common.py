"""collectors/common: ledger query engine, time buckets and the Host check."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("common")
from common import ledger, security  # noqa: E402

H = 3600 * 1000
NIGHT = 1795044600000  # 2026-11-18T23:30:00Z = 2026-11-19 00:30 in Madrid
ROWS = [
    {"ts": NIGHT, "project": "api", "model": "opus", "cost": 0.5, "messages": 1},
    {"ts": NIGHT - 12 * H, "project": "demo", "model": "sonnet", "cost": 0.25, "messages": 1},
    {"ts": NIGHT - 11 * H, "project": "demo", "model": "sonnet", "cost": 0.25, "messages": 1},
]


def q(**kw):
    return {k.replace("__", "."): [str(v)] for k, v in kw.items()}


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
