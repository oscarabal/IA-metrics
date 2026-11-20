"""Claude price table and cost estimate."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

helpers.use_collector("claude")
import pricing  # noqa: E402

DAY = 86400 * 1000
NOV = 1794960000000  # 2026-11-18
SEP = NOV - 60 * DAY


class Pricing(unittest.TestCase):
    def test_normalise(self):
        for raw, want in (("claude-sonnet-4-5-20250929", "claude-sonnet-4-5"), ("claude-opus-4-1-20250805[1m]", "claude-opus-4-1"),
                          ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5"), ("claude-opus-5-5", "claude-opus-5-5")):
            self.assertEqual(pricing.normalise(raw), want)

    def test_longest_prefix(self):
        self.assertEqual(pricing.period_for("claude-opus-4-1-20250805", NOV)["input"], 15)  # not claude-opus-4
        self.assertEqual(pricing.period_for("claude-sonnet-5-5", NOV)["input"], 2)          # not claude-sonnet-5

    def test_basic(self):
        # Sonnet 4.5: 100 in, 200 out, 5000 cache read, 300 cache write (5m)
        want = (100 * 3 + 200 * 15 + 5000 * 0.30 + 300 * 3.75) / 1e6
        self.assertAlmostEqual(pricing.cost("claude-sonnet-4-5-20250929", NOV, 100, 200, 5000, 300), want, places=12)

    def test_one_hour_writes(self):
        want = (100 * 6 + 200 * 3.75) / 1e6
        self.assertAlmostEqual(pricing.cost("claude-sonnet-4-5", NOV, 0, 0, 0, 300, {"w1h": 100}), want, places=12)

    def test_price_change_by_date(self):
        self.assertAlmostEqual(pricing.cost("claude-sonnet-5-5", SEP, 0, 0, 1_000_000, 0), 0.20, places=9)
        self.assertAlmostEqual(pricing.cost("claude-sonnet-5-5", NOV, 0, 0, 1_000_000, 0), 0.10, places=9)

    def test_tier_by_prompt_size(self):
        small = pricing.cost("claude-haiku-5-5", NOV, 50_000, 1000, 0, 0)
        big = pricing.cost("claude-haiku-5-5", NOV, 150_000, 1000, 0, 0)
        self.assertAlmostEqual(small, (50_000 * 0.10 + 1000 * 0.50) / 1e6, places=12)
        self.assertAlmostEqual(big, (150_000 * 0.50 + 1000 * 2.50) / 1e6, places=12)

    def test_fast_geo_and_search(self):
        fast = pricing.cost("claude-opus-5-5", NOV, 1_000_000, 1_000_000, 1_000_000, 0, {"fast": 1})
        self.assertAlmostEqual(fast, 8 + 40 + 0.20 * 2, places=9)
        geo = pricing.cost("claude-opus-5-5", NOV, 1_000_000, 0, 0, 0, {"geo_us": 1})
        self.assertAlmostEqual(geo, 4 * 1.1, places=9)
        self.assertAlmostEqual(pricing.cost("claude-opus-5-5", NOV, 0, 0, 0, 0, {"ws": 3}), 0.03, places=9)

    def test_unknown_model_is_missing(self):
        self.assertIsNone(pricing.cost("gpt-5", NOV, 1, 1, 1, 1))
        self.assertIsNone(pricing.cost("<synthetic>", NOV, 1, 1, 1, 1))

    def test_extras(self):
        self.assertEqual(pricing.usage_extras({"cache_creation": {"ephemeral_1h_input_tokens": 7}, "speed": "fast",
                                               "server_tool_use": {"web_search_requests": 2}}), {"w1h": 7, "fast": 1, "ws": 2})
        self.assertIsNone(pricing.usage_extras({"input_tokens": 3}))


if __name__ == "__main__":
    unittest.main()
