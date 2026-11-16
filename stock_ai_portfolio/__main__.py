"""Read bundled synthetic inputs and write a JSON report to stdout only."""
from datetime import date
import json
from pathlib import Path

from .evaluation import uncertainty
from .reconciliation import audit_snapshot, legacy_would_cancel
from .signals import NewsScore, emergency_review, rank_candidates, signal, utc_time

ROOT = Path(__file__).resolve().parents[1]


def build_report() -> dict:
    scenario = json.loads((ROOT / "data/synthetic_scenario.json").read_text(encoding="utf-8"))
    recorded = json.loads((ROOT / "data/verified_aggregates.json").read_text(encoding="utf-8"))
    news = [NewsScore(**n) for n in scenario["news"]]
    now = utc_time(scenario["as_of"])
    return {
        "mode": "offline_synthetic_review_only",
        "orders_supported": False,
        "model_inference_performed": False,
        "signals": [{**p, **signal(news, p["market"], p["symbol"], now)}
                    for p in scenario["predictions"]],
        "candidate_ranking": rank_candidates(scenario["predictions"], news, now),
        "emergency_reviews": [{**p, **emergency_review(news, p["market"], p["symbol"], now)}
                              for p in scenario["held"]],
        "legacy_friday_to_saturday_cancellation": legacy_would_cancel(
            date(2026, 7, 17), date(2026, 7, 18), False),
        "snapshot_findings": audit_snapshot(scenario["positions"], scenario["held"], scenario["orders"]),
        "documented_summary_arithmetic": {
            market: uncertainty(**values) for market, values in recorded["walkforward_documented"].items()},
    }


def main():
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
