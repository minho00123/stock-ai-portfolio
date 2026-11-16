# 가격 피처·학습·검증 원본 발췌

테스트 분기를 early stopping에도 사용하는 문제와 달력일 근사 청산은 원본 그대로다. 검증 완료된 개선 코드가 아니다.

아래는 로컬 원본의 선택된 줄을 그대로 옮긴 비실행 발췌다. 생략된 import·전역값·주변 코드는 포함하지 않았다. 출처와 해시는 [manifest.json](manifest.json)에 기록한다.

### `build_features.py` L42–L55

```python
def build_market_features(market_dir: str) -> pd.DataFrame:
    spy = pd.read_csv(f"{market_dir}/SPY.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    qqq = pd.read_csv(f"{market_dir}/QQQ.csv", parse_dates=["timestamp"]).set_index("timestamp").sort_index()

    mkt = pd.DataFrame(index=spy.index)
    mkt["spy_return_5d"] = spy["close"].pct_change(5)
    mkt["spy_return_20d"] = spy["close"].pct_change(20)
    mkt["spy_volatility_20d"] = spy["close"].pct_change().rolling(20).std()
    mkt["spy_close_to_ma50"] = spy["close"] / spy["close"].rolling(50).mean()
    mkt["spy_close_to_ma200"] = spy["close"] / spy["close"].rolling(200).mean()
    mkt["is_bull_market"] = (mkt["spy_close_to_ma200"] > 1).astype(int)
    mkt["qqq_return_5d"] = qqq["close"].pct_change(5)
    mkt["qqq_return_20d"] = qqq["close"].pct_change(20)
    return mkt
```

### `build_features.py` L58–L139

```python
def build_stock_features(df: pd.DataFrame, market: pd.DataFrame, sector: int) -> pd.DataFrame:
    out = df.copy()

    # ====== 기본 가격 피처 ======
    out["return_1d"] = out["close"].pct_change(1)
    out["return_5d"] = out["close"].pct_change(5)
    out["return_20d"] = out["close"].pct_change(20)

    out["close_to_ma5"] = out["close"] / out["close"].rolling(5).mean()
    out["close_to_ma20"] = out["close"] / out["close"].rolling(20).mean()
    out["close_to_ma60"] = out["close"] / out["close"].rolling(60).mean()

    out["volatility_5d"] = out["return_1d"].rolling(5).std()
    out["volatility_20d"] = out["return_1d"].rolling(20).std()
    out["intraday_range"] = (out["high"] - out["low"]) / out["close"]

    # ====== 기술적 지표 ======
    out["rsi_14"] = ta.momentum.RSIIndicator(out["close"], window=14).rsi()
    macd = ta.trend.MACD(out["close"])
    out["macd_diff"] = macd.macd_diff()
    bb = ta.volatility.BollingerBands(out["close"], window=20)
    out["bb_position"] = (out["close"] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())

    # ====== 신규: 추가 모멘텀 지표 ======
    stoch = ta.momentum.StochasticOscillator(out["high"], out["low"], out["close"], window=14)
    out["stoch_k"] = stoch.stoch()
    out["stoch_d"] = stoch.stoch_signal()

    out["williams_r"] = ta.momentum.WilliamsRIndicator(out["high"], out["low"], out["close"], lbp=14).williams_r()

    # ATR (변동성 절대값) - 종가 대비 정규화
    atr = ta.volatility.AverageTrueRange(out["high"], out["low"], out["close"], window=14)
    out["atr_pct"] = atr.average_true_range() / out["close"]

    # ADX (추세 강도)
    adx = ta.trend.ADXIndicator(out["high"], out["low"], out["close"], window=14)
    out["adx"] = adx.adx()

    # ====== 신규: 52주 고/저점 대비 위치 ======
    out["dist_from_252d_high"] = out["close"] / out["close"].rolling(252).max() - 1
    out["dist_from_252d_low"] = out["close"] / out["close"].rolling(252).min() - 1

    # 60일 고/저점도
    out["dist_from_60d_high"] = out["close"] / out["close"].rolling(60).max() - 1
    out["dist_from_60d_low"] = out["close"] / out["close"].rolling(60).min() - 1

    # ====== 신규: 캔들 패턴 (간단 버전) ======
    body = abs(out["close"] - out["open"])
    upper_shadow = out["high"] - out[["close", "open"]].max(axis=1)
    lower_shadow = out[["close", "open"]].min(axis=1) - out["low"]
    total_range = out["high"] - out["low"]

    out["body_ratio"] = body / total_range.replace(0, np.nan)
    out["upper_shadow_ratio"] = upper_shadow / total_range.replace(0, np.nan)
    out["lower_shadow_ratio"] = lower_shadow / total_range.replace(0, np.nan)

    # 양봉 여부
    out["is_bullish_candle"] = (out["close"] > out["open"]).astype(int)

    # ====== 신규: 요일 (월화수목금) ======
    out["day_of_week"] = out.index.dayofweek  # 0=월 ... 4=금

    # ====== 거래량 피처 ======
    out["volume_ratio"] = out["volume"] / out["volume"].rolling(20).mean()
    # 신규: 거래량 z-score (몇 σ 떨어졌나)
    vol_mean = out["volume"].rolling(20).mean()
    vol_std = out["volume"].rolling(20).std()
    out["volume_zscore"] = (out["volume"] - vol_mean) / vol_std

    # ====== 시장 컨텍스트 조인 ======
    out = out.join(market, how="left")
    out["rel_strength_5d"] = out["return_5d"] - out["spy_return_5d"]
    out["rel_strength_20d"] = out["return_20d"] - out["spy_return_20d"]

    # ====== 섹터 (categorical) ======
    out["sector"] = sector

    # ====== 라벨 ======
    out["future_return"] = out["close"].shift(-LABEL_HORIZON) / out["close"] - 1
    out["label"] = (out["future_return"] > LABEL_THRESHOLD).astype(int)

    return out
```

### `train_model.py` L62–L104

```python
split_date = df["timestamp"].quantile(0.8)
train = df[df["timestamp"] < split_date].copy()
test = df[df["timestamp"] >= split_date].copy()

print(f"\n학습: {len(train):,}행 (~{train['timestamp'].max().date()})")
print(f"테스트: {len(test):,}행 ({test['timestamp'].min().date()}~)")

X_train, y_train = train[FEATURE_COLS], train[TARGET]
X_test, y_test = test[FEATURE_COLS], test[TARGET]

# categorical 컬럼은 int로 변환
for col in CATEGORICAL_FEATURES:
    X_train[col] = X_train[col].astype("int")
    X_test[col] = X_test[col].astype("int")

# ------- 모델 학습 -------
model = lgb.LGBMClassifier(
    n_estimators=1000,
    learning_rate=0.03,
    max_depth=7,
    num_leaves=63,
    min_child_samples=50,
    class_weight="balanced",
    random_state=42,
    verbose=-1,
)

model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    categorical_feature=CATEGORICAL_FEATURES,
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
)

# ------- 평가 -------
pred = model.predict(X_test)
pred_proba = model.predict_proba(X_test)[:, 1]

print("\n" + "=" * 60)
print("모델 성능 (테스트셋)")
print("=" * 60)
print(f"Accuracy:   {accuracy_score(y_test, pred):.3f}")
print(f"Precision:  {precision_score(y_test, pred):.3f}  ← 매수 신호 중 진짜 오른 비율")
```

### `feature_selection.py` L91–L129

```python
}).sort_values("importance", ascending=False).reset_index(drop=True)

# ------- 2단계: 여러 N값으로 비교 -------
print("\n" + "=" * 60)
print("2단계: 상위 N개 피처로 재학습 비교")
print("=" * 60)

results = [full_result]
for n in [10, 15, 20, 25, 30]:
    top_features = importance.head(n)["feature"].tolist()
    r = train_and_eval(top_features, f"Top {n}")
    results.append(r)
    print(f"  Top {n:2d}:  Precision {r['precision']:.3f}, AUC {r['auc']:.3f}")

# ------- 결과 요약 + 최적 모델 저장 -------
print("\n" + "=" * 60)
print("결과 요약 (AUC 기준 정렬)")
print("=" * 60)
results_sorted = sorted(results, key=lambda x: x["auc"], reverse=True)
for r in results_sorted:
    print(f"  {r['name']:15s}  ({r['n_features']:2d}개)  Precision: {r['precision']:.3f}  AUC: {r['auc']:.3f}")

# 최적 모델 저장
best = results_sorted[0]
joblib.dump(best["model"], "models/lgbm_v1.pkl")
print(f"\n최적 모델 저장: {best['name']} ({best['n_features']}개 피처)")

# 선택된 피처 목록 저장 (백테스트에서 사용)
if best["n_features"] < len(ALL_FEATURES):
    best_features = importance.head(best["n_features"])["feature"].tolist()
else:
    best_features = ALL_FEATURES
with open("models/selected_features.txt", "w") as f:
    f.write("\n".join(best_features))
print(f"피처 목록 저장: models/selected_features.txt")

print("\n[선택된 피처]")
for i, feat in enumerate(best_features, 1):
    print(f"  {i:2d}. {feat}")
```

### `walkforward.py` L48–L125

```python
def run_window(train_df, test_df):
    """단일 윈도우 학습 + 백테스트"""
    X_train, y_train = train_df[FEATURES].copy(), train_df[TARGET]
    X_test, y_test = test_df[FEATURES].copy(), test_df[TARGET]

    cats_in_use = [c for c in CATEGORICAL if c in FEATURES]
    for col in cats_in_use:
        X_train[col] = X_train[col].astype("int")
        X_test[col] = X_test[col].astype("int")

    model = lgb.LGBMClassifier(
        n_estimators=1000, learning_rate=0.03,
        max_depth=7, num_leaves=63, min_child_samples=50,
        class_weight="balanced", random_state=42, verbose=-1,
    )

    fit_kwargs = {
        "eval_set": [(X_test, y_test)],
        "callbacks": [lgb.early_stopping(50), lgb.log_evaluation(0)],
    }
    if cats_in_use:
        fit_kwargs["categorical_feature"] = cats_in_use

    model.fit(X_train, y_train, **fit_kwargs)

    proba = model.predict_proba(X_test)[:, 1]
    test_df = test_df.copy()
    test_df["pred_proba"] = proba

    # 분기 내 일별 상위 N개 매수
    test_df["daily_rank"] = test_df.groupby("timestamp")["pred_proba"].rank(method="first", ascending=False)
    signals = test_df[test_df["daily_rank"] <= TOP_N_PER_DAY].copy()
    signals["net_return"] = signals["future_return"] - ROUND_TRIP_COST

    # 자본 시뮬레이션
    unique_dates = sorted(test_df["timestamp"].unique())
    capital = INITIAL_CAPITAL
    open_positions = []
    n_trades = 0
    pnls = []

    for date in unique_dates:
        # 만기 청산
        closing = [p for p in open_positions if p["exit_date"] <= date]
        for p in closing:
            capital += p["exit_value"]
            open_positions.remove(p)

        # 신호 매수
        todays = signals[signals["timestamp"] == date]
        slots = MAX_CONCURRENT - len(open_positions)
        for _, sig in todays.head(slots).iterrows():
            if capital < POSITION_SIZE:
                break
            capital -= POSITION_SIZE
            exit_value = POSITION_SIZE * (1 + sig["net_return"])
            exit_date = sig["timestamp"] + pd.Timedelta(days=HOLD_DAYS + 2)
            open_positions.append({"exit_date": exit_date, "exit_value": exit_value})
            pnls.append(POSITION_SIZE * sig["net_return"])
            n_trades += 1

    # 남은 포지션 청산
    for p in open_positions:
        capital += p["exit_value"]

    # 벤치마크: 동일가중
    bench_return = test_df.groupby("timestamp")["return_1d"].mean()
    bench_cum = (1 + bench_return).prod() - 1

    return {
        "return": (capital / INITIAL_CAPITAL - 1) * 100,
        "bench_return": bench_cum * 100,
        "alpha": (capital / INITIAL_CAPITAL - 1) * 100 - bench_cum * 100,
        "n_trades": n_trades,
        "win_rate": (np.array(pnls) > 0).mean() * 100 if pnls else 0,
        "precision": precision_score(test_df[TARGET], (test_df["pred_proba"] > 0.5).astype(int), zero_division=0),
        "auc": roc_auc_score(test_df[TARGET], test_df["pred_proba"]) if test_df[TARGET].nunique() > 1 else 0,
    }
```

### `backtest.py` L12–L24

```python
os.makedirs("charts", exist_ok=True)

# ------- 설정 -------
TOP_N_PER_DAY = 3            # 매일 확률 상위 N개 종목 매수
COMMISSION = 0.0005
SLIPPAGE = 0.0005
ROUND_TRIP_COST = 2 * (COMMISSION + SLIPPAGE)
INITIAL_CAPITAL = 100_000
POSITION_SIZE = 5_000
MAX_CONCURRENT = 15
HOLD_DAYS = 5

# 피처 선택 결과 자동 로드 (feature_selection.py에서 생성)
```

### `backtest.py` L65–L108

```python
        if capital < POSITION_SIZE:
            break
        capital -= POSITION_SIZE
        exit_value = POSITION_SIZE * (1 + sig["net_return"])
        exit_date = sig["timestamp"] + pd.Timedelta(days=HOLD_DAYS + 2)  # 영업일 보정

        open_positions.append({"exit_date": exit_date, "exit_value": exit_value})
        trade_log.append({
            "entry_date": sig["timestamp"],
            "symbol": sig["symbol"],
            "pred_proba": sig["pred_proba"],
            "future_return": sig["future_return"],
            "net_return": sig["net_return"],
            "pnl": POSITION_SIZE * sig["net_return"],
        })

    open_value = sum(p["exit_value"] for p in open_positions)
    equity_history.append({"date": date, "equity": capital + open_value})

# 남은 포지션 청산
for p in open_positions:
    capital += p["exit_value"]
final_equity = capital

# ------- 분석 -------
equity_df = pd.DataFrame(equity_history)
trades_df = pd.DataFrame(trade_log)

total_return = (final_equity / INITIAL_CAPITAL - 1) * 100
n_trades = len(trades_df)
win_rate = (trades_df["pnl"] > 0).mean() * 100
avg_win = trades_df[trades_df["pnl"] > 0]["pnl"].mean() if (trades_df["pnl"] > 0).any() else 0
avg_loss = trades_df[trades_df["pnl"] < 0]["pnl"].mean() if (trades_df["pnl"] < 0).any() else 0
profit_factor = (abs(trades_df[trades_df["pnl"] > 0]["pnl"].sum() /
                     trades_df[trades_df["pnl"] < 0]["pnl"].sum())
                 if (trades_df["pnl"] < 0).any() else float("inf"))

equity_df["peak"] = equity_df["equity"].cummax()
equity_df["drawdown"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"] * 100
mdd = equity_df["drawdown"].min()

# 벤치마크: SPY 대용으로 30종목 동일가중 매수후보유
bench_df = test.groupby("timestamp")["return_1d"].mean().reset_index()
bench_df["cumulative"] = (1 + bench_df["return_1d"]).cumprod() * INITIAL_CAPITAL
```

### `backtest_kr.py` L14–L24

```python
# ------- 설정 (한국 시장 기준 - 장기 보유 전략) -------
TOP_N_PER_DAY = 1              # 매일 가장 확신 큰 1종목만
COMMISSION = 0.00015
SLIPPAGE = 0.0005
TRANSACTION_TAX = 0.0018
ROUND_TRIP_COST = 2 * (COMMISSION + SLIPPAGE) + TRANSACTION_TAX
INITIAL_CAPITAL = 100_000_000
POSITION_SIZE = 5_000_000
MAX_CONCURRENT = 20            # 20일 × 1종목/일 = 최대 20포지션
HOLD_DAYS = 20                 # 4주 보유 (한국 시장 추세 추종)

```

