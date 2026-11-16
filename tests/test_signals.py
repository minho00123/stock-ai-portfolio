from datetime import datetime, timedelta, timezone
import unittest

from stock_ai_portfolio.signals import NewsScore, aggregate, emergency_review, rank_candidates, signal

NOW = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)


def news(sentiment, importance, hours=1, market="US", symbol="DEMO"):
    return NewsScore(market, symbol, (NOW - timedelta(hours=hours)).isoformat(), sentiment, importance)


class SignalTests(unittest.TestCase):
    def test_veto_inclusive_threshold(self):
        self.assertEqual(aggregate([news(-5, 5)] * 2)["decision"], "veto")

    def test_boost_inclusive_threshold(self):
        self.assertEqual(aggregate([news(5, 5)] * 2)["decision"], "boost")

    def test_low_importance_does_not_veto(self):
        self.assertEqual(aggregate([news(-10, 4)] * 2)["decision"], "neutral")

    def test_weighted_not_simple_average(self):
        score = aggregate([news(-8, 9), news(8, 1)])
        self.assertEqual(score["weighted_sentiment"], -6.4)
        self.assertEqual(score["decision"], "veto")

    def test_zero_weight_is_neutral(self):
        self.assertEqual(aggregate([news(10, 0)] * 2)["weighted_sentiment"], 0)

    def test_empty_or_single_news_neutral(self):
        for rows in [[], [news(-7, 8)]]:
            self.assertEqual(aggregate(rows)["decision"], "neutral")

    def test_window_market_symbol_and_future_exclusion(self):
        rows = [news(5, 5, 48), news(5, 5, 0), news(-10, 10, 48.001),
                news(-10, 10, -1), news(-10, 10, market="KR"), news(-10, 10, symbol="OTHER")]
        score = signal(rows, "US", "DEMO", NOW)
        self.assertEqual(score["n_news"], 2)
        self.assertEqual(score["decision"], "boost")

    def test_timezone_offsets_represent_same_instant(self):
        row = NewsScore("US", "DEMO", "2026-07-16T21:00:00+09:00", 5, 5)
        self.assertEqual(signal([row, row], "US", "DEMO", NOW)["n_news"], 2)

    def test_rejects_bad_llm_scores_and_naive_timestamp(self):
        for sent, imp in [(11, 5), (-11, 5), (1.5, 5), (True, 5), (1, -1), (1, 11)]:
            with self.subTest(sent=sent, imp=imp), self.assertRaises(ValueError):
                news(sent, imp)
        with self.assertRaises(ValueError):
            NewsScore("US", "DEMO", "2026-07-18T12:00:00", 0, 0)
        with self.assertRaises(ValueError):
            signal([], "US", "DEMO", NOW.replace(tzinfo=None))

    def test_single_major_event_can_require_review_without_veto(self):
        rows = [news(-7, 8, 72)]
        self.assertEqual(signal(rows, "US", "DEMO", NOW)["decision"], "neutral")
        result = emergency_review(rows, "US", "DEMO", NOW)
        self.assertTrue(result["review_required"])
        self.assertEqual(result["reason"], "single_major_event")

    def test_sustained_threshold(self):
        result = emergency_review([news(-6, 7)] * 2, "US", "DEMO", NOW)
        self.assertTrue(result["review_required"])
        self.assertEqual(result["reason"], "sustained")

    def test_ranking_filters_veto_and_applies_bonus(self):
        rows = [news(-5, 5, symbol="NEG")] * 2 + [news(5, 5, symbol="POS")] * 2
        candidates = [{"market": "US", "symbol": s, "model_score": p}
                      for s, p in [("NEG", 0.9), ("NONE", 0.61), ("POS", 0.58)]]
        ranked = rank_candidates(candidates, rows, NOW)
        self.assertEqual([r["symbol"] for r in ranked], ["POS", "NONE"])
        self.assertEqual(ranked[0]["ranking_score"], 0.63)
        self.assertEqual(candidates[0]["model_score"], 0.9)

    def test_bonus_is_not_a_probability(self):
        rows = [news(5, 5)] * 2
        result = rank_candidates([{"market": "US", "symbol": "DEMO", "model_score": 0.99}], rows, NOW)
        self.assertEqual(result[0]["ranking_score"], 1.04)

    def test_rejects_invalid_predictions(self):
        for value in [float("nan"), float("inf"), -0.1, 1.01, True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                rank_candidates([{"market": "US", "symbol": "DEMO", "model_score": value}], [], NOW)
