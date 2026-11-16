from copy import deepcopy
from datetime import date
import unittest

from stock_ai_portfolio.reconciliation import audit_snapshot, legacy_would_cancel


class ReconciliationTests(unittest.TestCase):
    def test_reproduces_weekend_cancellation_defect(self):
        self.assertTrue(legacy_would_cancel(date(2026, 7, 17), date(2026, 7, 18), False))

    def test_same_day_and_held_not_cancelled(self):
        self.assertFalse(legacy_would_cancel(date(2026, 7, 17), date(2026, 7, 17), False))
        self.assertFalse(legacy_would_cancel(date(2026, 7, 17), date(2026, 7, 18), True))

    def test_pending_is_not_assumed_cancelled(self):
        positions = [{"market": "US", "symbol": "DEMO", "status": "open"}]
        orders = [{"market": "US", "symbol": "DEMO", "status": "partially_filled"}]
        self.assertEqual(audit_snapshot(positions, [], orders)[0]["issue"], "awaiting_fill")

    def test_cancelled_record_with_holding_and_pending_flagged(self):
        row = {"market": "US", "symbol": "DEMO"}
        findings = audit_snapshot([{**row, "status": "cancelled"}], [row], [{**row, "status": "new"}])
        self.assertEqual({r["issue"] for r in findings},
                         {"untracked_holding", "pending_order_without_active_record"})

    def test_missing_holding_is_review_not_automatic_mutation(self):
        positions = [{"market": "US", "symbol": "DEMO", "status": "open"}]
        before = deepcopy(positions)
        self.assertEqual(audit_snapshot(positions, [], [])[0]["issue"], "missing_holding_requires_review")
        self.assertEqual(positions, before)

    def test_markets_are_separate(self):
        findings = audit_snapshot([{"market": "US", "symbol": "DEMO", "status": "open"}],
                                  [{"market": "KR", "symbol": "DEMO"}], [])
        self.assertEqual(len(findings), 2)

    def test_consistent_and_empty_snapshots(self):
        self.assertEqual(audit_snapshot([], [], []), [])
        row = {"market": "US", "symbol": "DEMO"}
        self.assertEqual(audit_snapshot([{**row, "status": "open"}], [row], []), [])
