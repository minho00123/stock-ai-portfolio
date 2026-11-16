import contextlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from stock_ai_portfolio.__main__ import build_report, main

ROOT = Path(__file__).resolve().parents[1]


def fingerprints():
    import hashlib
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


class DemoTests(unittest.TestCase):
    def test_full_demo_with_network_blocked_and_no_file_mutation(self):
        before = fingerprints()
        stream = io.StringIO()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")), \
                contextlib.redirect_stdout(stream):
            main()
        report = json.loads(stream.getvalue())
        self.assertFalse(report["orders_supported"])
        self.assertFalse(report["model_inference_performed"])
        self.assertTrue(report["legacy_friday_to_saturday_cancellation"])
        self.assertEqual(fingerprints(), before)

    def test_deterministic_and_expected_findings(self):
        report = build_report()
        self.assertEqual(report, build_report())
        self.assertEqual({f["issue"] for f in report["snapshot_findings"]},
                         {"untracked_holding", "pending_order_without_active_record",
                          "awaiting_fill", "missing_holding_requires_review"})
        us = [r for r in report["candidate_ranking"] if r["market"] == "US"]
        self.assertEqual([r["symbol"] for r in us], ["DEMO_US_POS", "DEMO_US_NONE"])
