"""Original thresholds from llm_signals.py/emergency_exit.py, rebuilt for offline use.

New in this portfolio: strict score validation, explicit clock, market separation,
UTC timestamp comparisons and exclusion of future news. No model is invoked.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math


def utc_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class NewsScore:
    market: str
    symbol: str
    published_at: str
    sentiment: int
    importance: int

    def __post_init__(self):
        if self.market not in {"US", "KR"} or not self.symbol:
            raise ValueError("invalid market or symbol")
        if type(self.sentiment) is not int or not -10 <= self.sentiment <= 10:
            raise ValueError("sentiment must be an integer from -10 to 10")
        if type(self.importance) is not int or not 0 <= self.importance <= 10:
            raise ValueError("importance must be an integer from 0 to 10")
        utc_time(self.published_at)


def recent_news(news: list[NewsScore], market: str, symbol: str,
                now: datetime, hours: int) -> list[NewsScore]:
    if now.tzinfo is None or now.utcoffset() is None or hours <= 0:
        raise ValueError("explicit timezone and positive window required")
    now = now.astimezone(timezone.utc)
    return [n for n in news if n.market == market and n.symbol == symbol
            and now - timedelta(hours=hours) <= utc_time(n.published_at) <= now]


def aggregate(rows: list[NewsScore]) -> dict:
    # Original signal helper ignores aggregates with fewer than two news items.
    if len(rows) < 2:
        return {"n_news": len(rows), "weighted_sentiment": 0,
                "max_importance": 0, "decision": "neutral"}
    weight = sum(n.importance for n in rows) or 1
    weighted = sum(n.sentiment * n.importance for n in rows) / weight
    max_importance = max(n.importance for n in rows)
    decision = "neutral"
    if weighted <= -5 and max_importance >= 5:
        decision = "veto"
    elif weighted >= 5 and max_importance >= 5:
        decision = "boost"
    return {"n_news": len(rows), "weighted_sentiment": round(weighted, 2),
            "max_importance": max_importance, "decision": decision}


def signal(news: list[NewsScore], market: str, symbol: str, now: datetime) -> dict:
    return aggregate(recent_news(news, market, symbol, now, 48))


def emergency_review(news: list[NewsScore], market: str, symbol: str,
                     now: datetime) -> dict:
    rows = recent_news(news, market, symbol, now, 72)
    score = aggregate(rows)
    sustained = score["weighted_sentiment"] <= -6 and score["max_importance"] >= 7
    # A single severe news item can trigger this branch despite neutral aggregate.
    mega = any(n.sentiment <= -7 and n.importance >= 8 for n in rows)
    return {"review_required": sustained or mega,
            "reason": "sustained" if sustained else "single_major_event" if mega else "none",
            "n_news": len(rows)}


def rank_candidates(predictions: list[dict], news: list[NewsScore], now: datetime) -> list[dict]:
    results = []
    seen = set()
    for row in predictions:
        market, symbol = row["market"], row["symbol"]
        if market not in {"US", "KR"} or not symbol or (market, symbol) in seen:
            raise ValueError("invalid or duplicate candidate")
        seen.add((market, symbol))
        value = row["model_score"]
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("model score must be finite and between 0 and 1")
        score = signal(news, market, symbol, now)
        if score["decision"] == "veto":
            continue
        # Original +0.05 is a ranking adjustment, not a calibrated probability.
        results.append({"market": market, "symbol": symbol, "model_score": value,
                        "ranking_score": round(value + (0.05 if score["decision"] == "boost" else 0), 6),
                        "news_decision": score["decision"]})
    return sorted(results, key=lambda r: (r["market"], -r["ranking_score"], r["symbol"]))
