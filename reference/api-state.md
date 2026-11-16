# 외부 API·상태 동기화 원본 발췌

실제 자격증명·계좌 식별자 없이 로직만 발췌했다. 주문 코드는 실행 파일로 배포하지 않는다. 이 문서의 함수를 실행하는 방법은 제공하지 않는다.

아래는 로컬 원본의 선택된 줄을 그대로 옮긴 비실행 발췌다. 생략된 import·전역값·주변 코드는 포함하지 않았다. 출처와 해시는 [manifest.json](manifest.json)에 기록한다.

### `kis_api.py` L31–L41

```python
def _load_cached_token() -> str | None:
    if not TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE.read_text())
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now() < expires_at - timedelta(minutes=10):
            return data["token"]
    except Exception:
        pass
    return None
```

### `kis_api.py` L86–L103

```python
def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 15)
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt:
            wait = RETRY_WAIT_SEC[attempt - 1]
            print(f"   ↻ KIS 재시도 {attempt}/{MAX_RETRIES} ({wait}초 대기) — {last_err}")
            time.sleep(wait)
        try:
            r = requests.request(method, url, **kwargs)
            if r.status_code >= 500:
                last_err = f"{r.status_code} {r.reason}"
                continue
            r.raise_for_status()
            return r
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = f"{type(e).__name__}: {e}"
    raise RuntimeError(f"KIS 요청 실패 (재시도 {MAX_RETRIES}회 소진): {method} {url} — {last_err}")
```

### `kis_api.py` L170–L191

```python
def buy_market(symbol: str, qty: int) -> dict:
    """시장가 매수"""
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    body = {
        "CANO": ACCOUNT_NO,
        "ACNT_PRDT_CD": ACCOUNT_PRODUCT,
        "PDNO": symbol,
        "ORD_DVSN": "01",  # 01=시장가, 00=지정가
        "ORD_QTY": str(qty),
        "ORD_UNPR": "0",
    }
    # 모의 매수 TR ID: VTTC0802U (실전: TTTC0802U)
    r = _request_with_retry("POST", url, headers=_headers("VTTC0802U"), json=body)
    data = r.json()
    if data["rt_cd"] != "0":
        raise RuntimeError(f"매수 실패: {data['msg1']}")
    return {
        "order_no": data["output"]["ODNO"],
        "symbol": symbol,
        "qty": qty,
        "side": "BUY",
    }
```

### `daily_trader.py` L178–L242

```python
def reconcile_positions(conn):
    """브로커 잔고와 DB를 대조해 포지션 상태를 확정한다.
    1) 'closing'/'emergency_close'인데 잔고에 없으면 → 매도 체결 완료.
       체결가(filled_avg_price)로 exit_price/pnl 기록, 'closing'은 'closed'로 전환.
    2) 'open'인데 잔고에 없고 진입일이 지난 포지션 → 매수 미체결(만료/거부)로 'cancelled' 처리.
       (이게 없으면 슬롯이 영구 점유되어 MAX_POSITIONS 도달 후 매매가 멈춘다)
    3) 보유 중 포지션의 entry_price를 실제 체결가로 보정 (신호가≠체결가 갭 보정)"""
    print(f"\n[0.5] 포지션 상태 동기화...")
    held = {p.symbol for p in trading_client.get_all_positions()}
    today = datetime.now(timezone.utc).date()
    c = conn.cursor()

    def filled_price(symbol, side):
        """trade_actions의 최근 주문 ID로 실제 체결가 조회. 실패 시 None."""
        row = c.execute(
            "SELECT order_id FROM trade_actions WHERE symbol=? AND side=? ORDER BY timestamp DESC LIMIT 1",
            (symbol, side)).fetchone()
        if not (row and row[0]):
            return None
        try:
            order = trading_client.get_order_by_id(row[0])
            if order.filled_avg_price:
                return float(order.filled_avg_price)
        except Exception as e:
            print(f"   ⚠️ {symbol} 주문 조회 실패: {e}")
        return None

    # 1) 매도 체결 확정
    rows = c.execute("""SELECT id, symbol, entry_price, qty, status FROM positions
                        WHERE status IN ('closing', 'emergency_close') AND pnl IS NULL""").fetchall()
    for pos_id, symbol, entry_price, qty, status in rows:
        if symbol in held:
            continue  # 아직 미체결 — 다음 실행에서 재확인
        exit_price = filled_price(symbol, "SELL")
        pnl = round((exit_price - entry_price) * qty, 2) if (exit_price and entry_price) else None
        new_status = "closed" if status == "closing" else status  # emergency_close 라벨은 유지
        c.execute("UPDATE positions SET status=?, exit_price=?, pnl=? WHERE id=?",
                  (new_status, exit_price, pnl, pos_id))
        pnl_str = f"${pnl:+,.2f}" if pnl is not None else "?"
        print(f"   ✔ {symbol} 청산 확정 (체결가 {exit_price}, 손익 {pnl_str})")

    # 2) 매수 미체결 포지션 정리 (슬롯 누수 방지)
    rows = c.execute("SELECT id, symbol, entry_date FROM positions WHERE status='open'").fetchall()
    for pos_id, symbol, entry_date in rows:
        if symbol in held:
            continue
        if entry_date >= today.isoformat():
            continue  # 당일 주문은 다음 개장 때 체결될 수 있음 — 대기
        c.execute("UPDATE positions SET status='cancelled' WHERE id=?", (pos_id,))
        print(f"   ✘ {symbol} 매수 미체결(만료/거부) — cancelled 처리")

    # 3) 진입가를 실제 체결가로 보정 (최근 3일 진입분만 — API 호출 최소화)
    cutoff = (today - timedelta(days=3)).isoformat()
    rows = c.execute("SELECT id, symbol, entry_price FROM positions WHERE status='open' AND entry_date >= ?",
                     (cutoff,)).fetchall()
    for pos_id, symbol, entry_price in rows:
        if symbol not in held:
            continue
        fill = filled_price(symbol, "BUY")
        if fill and entry_price and abs(fill - entry_price) > 0.005:
            c.execute("UPDATE positions SET entry_price=? WHERE id=?", (fill, pos_id))
            print(f"   ↺ {symbol} 진입가 보정: {entry_price:.2f} → {fill:.2f}")

    conn.commit()
    print(f"   동기화 완료 (보유 {len(held)}종목)")
```

### `daily_trader.py` L394–L410

```python
    try:
        # 동기화는 휴장일에도 실행 — 연휴 직전 매도 체결이 'closing' 상태로
        # 방치되는 것 방지 (7/2 매도 → 7/3 휴장 연휴에 NVDA·BA 미확정 사례)
        reconcile_positions(conn)

        # [0] 미국 거래일 여부 체크 (주말·공휴일이면 신규/청산 매매 스킵)
        #     한국 06:00 = 미국 동부 전날 저녁(장 마감 후)이라, 미국 동부 '오늘' 날짜가
        #     거래일인지 보면 미국 거래일당 정확히 1회만 실행된다(주말 중복 주문 방지).
        et_today = datetime.now(ZoneInfo("America/New_York")).date()
        cal = trading_client.get_calendar(GetCalendarRequest(start=et_today, end=et_today))
        if not cal:
            print(f"\n[0] {et_today} (미국 동부) — 휴장일. 미국 매매 스킵.")
            return

        clock = trading_client.get_clock()
        print(f"\n[0] 미국 거래일 ✓  시장 상태: {'OPEN' if clock.is_open else 'CLOSED'}")
        print(f"   다음 개장: {clock.next_open}")
```

### `daily_trader.py` L351–L371

```python
        qty = round(POSITION_SIZE_USD / price, 4)  # fractional shares
        try:
            order = MarketOrderRequest(
                symbol=symbol, qty=qty,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            result = trading_client.submit_order(order)
            c.execute(
                """INSERT INTO positions(symbol, entry_date, entry_price, qty, pred_proba, target_exit_date, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'open')""",
                (symbol, today.isoformat(), price, qty, proba, target_exit),
            )
            c.execute(
                "INSERT INTO trade_actions(timestamp, symbol, side, qty, order_id, note) VALUES (?, ?, 'BUY', ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), symbol, qty, str(result.id),
                 f"매수 (proba {proba:.4f}, rank {rank})"),
            )
            # 마지막 신호 acted=1로 업데이트
            c.execute(
                "UPDATE signals SET acted=1 WHERE date=? AND symbol=?",
                (today.isoformat(), symbol),
```

### `daily_trader_kr.py` L215–L256

```python
def reconcile_positions(conn):
    """KIS 잔고와 DB를 대조해 포지션 상태를 확정한다.
    1) 'closing'/'emergency_close'인데 잔고에 없으면 → 매도 체결 완료.
       KIS 체결조회 API 미구현이라 현재가로 체결가를 근사해 exit_price/pnl 기록.
    2) 'open'인데 잔고에 없고 진입일이 지난 포지션 → 주문 미체결로 'cancelled' 처리.
       (이게 없으면 슬롯이 영구 점유되어 MAX_POSITIONS 도달 후 매매가 멈춘다)"""
    print(f"\n[0.5] 포지션 상태 동기화...")
    bal = kis_api.get_balance()
    held = {p["symbol"] for p in bal["positions"]}
    today = kr_today()
    c = conn.cursor()

    # 1) 매도 체결 확정
    rows = c.execute("""SELECT id, symbol, entry_price, qty, status FROM positions
                        WHERE status IN ('closing', 'emergency_close') AND pnl IS NULL""").fetchall()
    for pos_id, symbol, entry_price, qty, status in rows:
        if symbol in held:
            continue  # 아직 미체결 — 다음 실행에서 재확인
        exit_price = None
        try:
            exit_price = kis_api.get_current_price(symbol)["price"]  # 체결가 근사 (매도 직후 현재가)
        except Exception as e:
            print(f"   ⚠️ {symbol} 현재가 조회 실패: {e}")
        pnl = (exit_price - entry_price) * qty if (exit_price and entry_price) else None
        new_status = "closed" if status == "closing" else status  # emergency_close 라벨은 유지
        c.execute("UPDATE positions SET status=?, exit_price=?, pnl=? WHERE id=?",
                  (new_status, exit_price, pnl, pos_id))
        pnl_str = f"{pnl:+,}원" if pnl is not None else "?"
        print(f"   ✔ {symbol} 청산 확정 (체결가≈{exit_price}, 손익 {pnl_str})")

    # 2) 매수 미체결 포지션 정리 (슬롯 누수 방지)
    rows = c.execute("SELECT id, symbol, entry_date FROM positions WHERE status='open'").fetchall()
    for pos_id, symbol, entry_date in rows:
        if symbol in held:
            continue
        if entry_date >= today.isoformat():
            continue  # 당일 주문은 체결 대기 가능성 — 다음 실행에서 재확인
        c.execute("UPDATE positions SET status='cancelled' WHERE id=?", (pos_id,))
        print(f"   ✘ {symbol} 매수 미체결(만료/거부) — cancelled 처리")

    conn.commit()
    print(f"   동기화 완료 (보유 {len(held)}종목)")
```

### `daily_trader_kr.py` L299–L306

```python
    c = conn.cursor()
    n_open = c.execute("SELECT COUNT(*) FROM positions WHERE status IN ('open','closing')").fetchone()[0]
    slots = MAX_POSITIONS - n_open
    print(f"   예수금: {cash:,}원, 빈 슬롯: {slots}")

    candidates = predictions_df.head(TOP_N_PER_DAY * 3)
    today = kr_today()
    target_exit = (today + timedelta(days=int(HOLD_DAYS * 1.5))).isoformat()  # 영업일 보정
```

