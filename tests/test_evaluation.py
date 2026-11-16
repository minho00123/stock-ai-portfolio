import json
from pathlib import Path
import unittest

from stock_ai_portfolio.evaluation import uncertainty

ROOT = Path(__file__).resolve().parents[1]


class EvaluationTests(unittest.TestCase):
    def test_us_summary_arithmetic(self):
        result = uncertainty(1.71, 6.7, 13)
        self.assertAlmostEqual(result["standard_error_pp"], 1.8582, places=3)
        self.assertAlmostEqual(result["t_statistic"], 0.9202, places=3)
        self.assertTrue(result["interval_includes_zero"])

    def test_kr_summary_arithmetic(self):
        result = uncertainty(0.83, 13.2, 13)
        self.assertAlmostEqual(result["t_statistic"], 0.2267, places=3)
        self.assertTrue(result["interval_includes_zero"])

    def test_invalid_summary_rejected(self):
        for args in [(1, 0, 13), (1, 2, 1), (1, 2, 2.5), (float("nan"), 2, 13)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                uncertainty(*args)

    def test_aggregate_keeps_missing_pnl_visible(self):
        recorded = json.loads((ROOT / "data/verified_aggregates.json").read_text())
        groups = recorded["local_db_aggregates"]["KR"]["groups"]
        closed = next(g for g in groups if g["status"] == "closed")
        self.assertEqual((closed["rows"], closed["pnl_present"]), (3, 2))
        model_counts = recorded["news_db_aggregate"]["model_counts"]
        self.assertEqual(sum(model_counts.values()), recorded["news_db_aggregate"]["analyzed_rows"])
