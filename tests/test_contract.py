"""Both collectors' improvement reports follow the same contract (ADR 0001/0004)."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

SNIPPET = r"""
import json, os, sys
sys.path.insert(0, %(here)r)
import helpers
helpers.use_collector(%(name)r)
import fixtures
tmp = helpers.tmpdir()
if %(name)r == "opencode":
    p = fixtures.make_opencode(tmp)
    os.environ.update(OPENCODE_DB=p["db"], OPENCODE_MODELS=p["models"], OPENCODE_COMMANDS_DIR=p["commands"], OPENCODE_QUOTA_DIR=p["quota"])
    import test_opencode as t
else:
    import test_claude as t
t.warm()
srv = helpers.Server(t.exporter.Handler if %(name)r == "opencode" else t.collector.Handler)
r = srv.json("/report.json")
from coach import report as coach_report
print(json.dumps({"keys": sorted(r), "summary": sorted(r["summary"]), "version": r["format_version"],
                  "rules": sorted(coach_report.RULES), "names": coach_report.RULES}))
"""


def report_of(name):
    out = subprocess.run([sys.executable, "-c", SNIPPET % {"here": HERE, "name": name}], capture_output=True, text=True, timeout=300)
    if out.returncode:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


class ReportContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc, cls.oc = report_of("claude"), report_of("opencode")

    def test_same_version(self):
        self.assertEqual(self.cc["version"], self.oc["version"])

    def test_same_top_level_keys(self):
        self.assertEqual(self.cc["keys"], self.oc["keys"])

    def test_shared_rules(self):
        shared = {"D%d" % i for i in range(1, 11)}
        self.assertTrue(shared <= set(self.cc["rules"]), set(self.cc["rules"]))
        self.assertTrue(shared <= set(self.oc["rules"]), set(self.oc["rules"]))

    def test_shared_rules_same_meaning(self):
        """D1-D10 mean the same in both tools, except D2, which each tool focuses on its own dimension."""
        for rid in ("D%d" % i for i in (1, 3, 4, 5, 6, 7, 8, 9, 10)):
            self.assertEqual(self.cc["names"][rid], self.oc["names"][rid], rid)


if __name__ == "__main__":
    unittest.main()
