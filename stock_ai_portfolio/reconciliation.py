"""Historical cancellation reproduction and NEW read-only consistency checks.

Checks report inconsistencies only. No order or database mutation is implemented.
Symbol-level checking intentionally does not claim fill/lot/quantity reconciliation.
"""
from datetime import date


def legacy_would_cancel(entry_date: date, today: date, symbol_is_held: bool) -> bool:
    """Reproduce the original open-row cancellation condition, including its defect."""
    return not symbol_is_held and entry_date < today


def audit_snapshot(positions: list[dict], held: list[dict], orders: list[dict]) -> list[dict]:
    """NEW portfolio proposal: compare supplied synthetic snapshots without changing them."""
    findings = []
    active = {(p["market"], p["symbol"]) for p in positions
              if p["status"] in {"open", "closing", "emergency_close"}}
    held_symbols = {(p["market"], p["symbol"]) for p in held}
    pending = {(p["market"], p["symbol"]) for p in orders
               if p["status"] in {"accepted", "pending_new", "new", "partially_filled"}}
    for market, symbol in sorted(held_symbols - active):
        findings.append({"market": market, "symbol": symbol, "issue": "untracked_holding"})
    for market, symbol in sorted(pending - active):
        findings.append({"market": market, "symbol": symbol, "issue": "pending_order_without_active_record"})
    for p in positions:
        key = (p["market"], p["symbol"])
        if p["status"] == "open" and key not in held_symbols:
            findings.append({"market": key[0], "symbol": key[1],
                             "issue": "awaiting_fill" if key in pending else "missing_holding_requires_review"})
    return findings
