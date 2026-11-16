# 뉴스·LLM 신호 원본 발췌

점수 범위 검증 부재와 문자열 시간 비교 등 원본 제약이 포함된다. SDK 호출 부분은 문서 안의 정적 코드다.

아래는 로컬 원본의 선택된 줄을 그대로 옮긴 비실행 발췌다. 생략된 import·전역값·주변 코드는 포함하지 않았다. 출처와 해시는 [manifest.json](manifest.json)에 기록한다.

### `news_collector.py` L69–L70

```python
def make_id(symbol: str, headline: str, published_at: str) -> str:
    return hashlib.sha256(f"{symbol}|{headline}|{published_at}".encode()).hexdigest()[:16]
```

### `news_collector.py` L162–L180

```python
def save_news(conn, items: list) -> int:
    """중복 무시하고 저장. 새로 저장된 행 수 반환."""
    cur = conn.cursor()
    saved = 0
    for it in items:
        nid = make_id(it["symbol"], it["headline"], it["published_at"])
        try:
            cur.execute(
                """INSERT INTO news(id, market, symbol, published_at, headline, summary, url, source, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, it["market"], it["symbol"], it["published_at"],
                 it["headline"], it["summary"], it["url"], it["source"],
                 datetime.now(timezone.utc).isoformat()),
            )
            saved += 1
        except sqlite3.IntegrityError:
            pass  # 중복
    conn.commit()
    return saved
```

### `llm_analyzer.py` L23–L34

```python
SYSTEM_PROMPT = """You are a financial news analyst. Analyze each news item and return STRICT JSON.

For each news, output:
{
  "sentiment": <integer -10 to +10>,  // -10=매우 악재, 0=중립, +10=매우 호재
  "importance": <integer 0 to 10>,    // 0=무관, 10=주가에 결정적 영향
  "event_type": "<string>",           // earnings | m&a | regulation | product | management | macro | analyst | normal
  "horizon": "<string>"               // immediate | short_term | long_term
}

Only output JSON, no explanations.
Be conservative — most news is "normal" with importance 0-3."""
```

### `llm_analyzer.py` L57–L68

```python
def get_unanalyzed(conn, limit: int = 100) -> list:
    """아직 분석 안 된 뉴스. 최신 우선."""
    rows = conn.execute("""
        SELECT n.id, n.market, n.symbol, n.headline, n.summary
        FROM news n
        LEFT JOIN news_analysis a ON n.id = a.news_id
        WHERE a.news_id IS NULL
        ORDER BY n.published_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [{"id": r[0], "market": r[1], "symbol": r[2],
             "headline": r[3], "summary": r[4] or ""} for r in rows]
```

### `llm_analyzer.py` L71–L102

```python
def analyze_one(client: Anthropic, news: dict) -> dict | None:
    """Claude 호출. 실패 시 None."""
    market_label = "US stock" if news["market"] == "US" else "Korean stock (KOSPI)"
    user_msg = (
        f"Market: {market_label}\n"
        f"Symbol: {news['symbol']}\n"
        f"Headline: {news['headline']}\n"
        f"Summary: {news['summary'][:500]}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # JSON 부분만 추출
        if text.startswith("```"):
            text = text.split("```")[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        result = json.loads(text)
        return {
            "sentiment": int(result.get("sentiment", 0)),
            "importance": int(result.get("importance", 0)),
            "event_type": str(result.get("event_type", "normal"))[:20],
            "horizon": str(result.get("horizon", "short_term"))[:20],
        }
    except Exception as e:
        print(f"   ⚠️ 분석 실패 ({news['symbol']}): {e}")
        return None
```

### `llm_signals.py` L26–L93

```python
def get_llm_score(symbol: str, hours: int = LOOKBACK_HOURS) -> dict:
    """
    종목의 LLM 점수 집계.
    반환: {
        'n_news': int,
        'avg_sentiment': float,
        'weighted_sentiment': float,  # 중요도 가중
        'max_importance': int,
        'has_major_event': bool,
        'decision': 'veto' | 'boost' | 'neutral',
        'top_news': [(headline, sentiment, importance), ...]
    }
    """
    if not DB_PATH.exists():
        return _neutral_response()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        # news_analysis 테이블 존재 확인
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_analysis'"
        ).fetchone()
        if not has_table:
            return _neutral_response()
        rows = conn.execute("""
            SELECT n.headline, n.published_at,
                   a.sentiment, a.importance, a.event_type
            FROM news n
            JOIN news_analysis a ON n.id = a.news_id
            WHERE n.symbol = ? AND n.published_at >= ?
            ORDER BY a.importance DESC, n.published_at DESC
        """, (symbol, cutoff)).fetchall()
    finally:
        conn.close()

    if not rows or len(rows) < MIN_NEWS_FOR_SIGNAL:
        return _neutral_response(n_news=len(rows))

    sentiments = [r[2] for r in rows]
    importances = [r[3] for r in rows]

    # 단순 평균
    avg_sent = sum(sentiments) / len(sentiments)

    # 중요도 가중 평균 (중요한 뉴스가 더 영향)
    total_weight = sum(importances) or 1
    weighted_sent = sum(s * w for s, w in zip(sentiments, importances)) / total_weight

    max_imp = max(importances)
    has_major = any(i >= 7 for i in importances)

    # 결정 로직
    decision = "neutral"
    if weighted_sent <= VETO_SENTIMENT and max_imp >= 5:
        decision = "veto"
    elif weighted_sent >= BOOST_SENTIMENT and max_imp >= 5:
        decision = "boost"

    return {
        "n_news": len(rows),
        "avg_sentiment": round(avg_sent, 2),
        "weighted_sentiment": round(weighted_sent, 2),
        "max_importance": max_imp,
        "has_major_event": has_major,
        "decision": decision,
        "top_news": [(r[0][:80], r[2], r[3]) for r in rows[:3]],
    }
```

### `llm_signals.py` L108–L139

```python
def apply_llm_filter(predictions_df, symbol_col: str = "symbol") -> tuple:
    """
    예측 DataFrame을 받아서 LLM 필터 적용.
    - veto 종목은 후보에서 제거
    - boost 종목은 pred_proba에 보너스
    반환: (filtered_df, log)
    """
    log = []
    df = predictions_df.copy()
    df["llm_decision"] = "neutral"
    df["llm_sentiment"] = 0.0
    df["llm_news_count"] = 0

    for idx, row in df.iterrows():
        symbol = row[symbol_col]
        score = get_llm_score(symbol)
        df.at[idx, "llm_decision"] = score["decision"]
        df.at[idx, "llm_sentiment"] = score["weighted_sentiment"]
        df.at[idx, "llm_news_count"] = score["n_news"]

        if score["decision"] == "boost":
            # 확률에 보너스 (0.05 만큼)
            df.at[idx, "pred_proba"] = float(row["pred_proba"]) + 0.05
            log.append(f"📈 BOOST {symbol}: 가중감성 {score['weighted_sentiment']:+.1f}, 뉴스 {score['n_news']}건")
        elif score["decision"] == "veto":
            log.append(f"🚫 VETO {symbol}: 가중감성 {score['weighted_sentiment']:+.1f}, 뉴스 {score['n_news']}건")

    # veto된 종목 제거
    df = df[df["llm_decision"] != "veto"]
    # 보너스 반영 재정렬
    df = df.sort_values("pred_proba", ascending=False).reset_index(drop=True)
    return df, log
```

### `emergency_exit.py` L45–L78

```python
def check_emergency(symbol: str) -> tuple:
    """비상 매도 필요 여부 + 사유 반환"""
    score = get_llm_score(symbol, hours=72)  # 최근 3일

    if score["n_news"] == 0:
        return False, "no news"

    # 조건 1: 지속적 강한 악재
    if (score["weighted_sentiment"] <= EMERGENCY_WEIGHTED_THRESHOLD
        and score["max_importance"] >= EMERGENCY_MIN_IMPORTANCE):
        return True, f"지속 악재 (가중 {score['weighted_sentiment']:+.1f}, 최대중요도 {score['max_importance']})"

    # 조건 2: 단일 메가 악재
    if not NEWS_DB.exists():
        return False, "DB 없음"
    conn = sqlite3.connect(NEWS_DB)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        mega = conn.execute("""
            SELECT n.headline, a.sentiment, a.importance, a.event_type
            FROM news n JOIN news_analysis a ON n.id = a.news_id
            WHERE n.symbol = ? AND n.published_at >= ?
              AND a.sentiment <= ? AND a.importance >= ?
            ORDER BY a.importance DESC, a.sentiment ASC
            LIMIT 1
        """, (symbol, cutoff, MEGA_EVENT_SENTIMENT, MEGA_EVENT_IMPORTANCE)).fetchone()
    finally:
        conn.close()

    if mega:
        headline, sent, imp, evt = mega
        return True, f"메가 악재 [{evt}] {sent}/{imp} — {headline[:60]}"

    return False, f"정상 (가중 {score['weighted_sentiment']:+.1f}, 뉴스 {score['n_news']}건)"
```

