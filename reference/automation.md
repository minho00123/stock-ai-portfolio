# 자동 실행 원본 발췌

원본 운영을 설명하는 텍스트다. 포트폴리오에서 shell 또는 cron으로 실행하지 않는다. lock은 사이클별이며 공통 DB에 대한 전역 잠금이 아니다.

아래는 로컬 원본의 선택된 줄을 그대로 옮긴 비실행 발췌다. 생략된 import·전역값·주변 코드는 포함하지 않았다. 출처와 해시는 [manifest.json](manifest.json)에 기록한다.

### `run_morning.sh` L1–L49

```bash
#!/bin/bash
# 아침 사이클 (KST 06:00 권장 — UTC 서버 cron이면 21:00 전날)
# - 뉴스 수집 + LLM 분석 + 비상 매도 + 미국 자동매매 + 미국 리포트
#
# ⚠️ 한국 매매/리포트는 여기 없음 — KIS는 장외 주문을 거부하므로
#    run_kr_trading.sh 를 KST 09:05 별도 cron으로 실행한다.
#
# ⚠️ set -e 를 쓰지 않는다: 한 단계(예: 자동매매)가 실패해도
#    이후 단계(특히 리포트/텔레그램 알림)는 계속 실행되어야 하기 때문.

cd "$(dirname "$0")"
PY="./venv/bin/python"

# 동시 실행 방지 (Linux flock; macOS 등 flock 없으면 건너뜀)
if command -v flock >/dev/null 2>&1; then
    exec 9>"/tmp/stock-ai-morning.lock"
    if ! flock -n 9; then
        echo "이미 실행 중 — 중복 실행 방지를 위해 종료"
        exit 0
    fi
fi

# run_step <라벨> <스크립트.py>
# 실패해도 다음 단계 계속 진행, 실패 시 텔레그램 에러 알림.
run_step() {
    local label="$1"
    local script="$2"
    echo ""
    echo "▶ $label"
    if ! $PY "$script"; then
        echo "⚠️ 실패: $label ($script) — 다음 단계 계속 진행"
        $PY -c "import notifier; notifier.error_alert('$script', '$label 단계가 0이 아닌 종료코드로 실패했습니다. 서버 로그를 확인하세요.')" 2>/dev/null || true
    fi
}

echo "============================================================"
echo "  아침 사이클 (미국) — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"

run_step "[1/5] 뉴스 수집"     news_collector.py
run_step "[2/5] LLM 분석"      llm_analyzer.py
run_step "[3/5] 비상 매도 체크" emergency_exit.py
run_step "[4/5] 미국 자동매매"   daily_trader.py
run_step "[5/5] 미국 리포트"     daily_report.py

echo ""
echo "============================================================"
echo "  아침 사이클 완료 — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"
```

### `run_kr_trading.sh` L1–L11

```bash
#!/bin/bash
# 한국 매매 사이클 (KST 09:05 권장 — UTC 서버 cron이면 00:05)
# - 뉴스 수집(최신화) + LLM 분석 + 한국 자동매매 + 한국 리포트
#
# KIS는 장외 시간 시장가 주문을 거부(큐잉 X)하므로
# 반드시 정규장(09:00~15:20 KST) 안에서 실행해야 한다.
# daily_trader_kr.py 자체에도 장중 가드가 있어 장외 실행 시 안전하게 스킵된다.
#
# ⚠️ set -e 를 쓰지 않는다: 매매가 실패해도 리포트는 항상 시도되어야 하기 때문.

cd "$(dirname "$0")"
```

### `run_intraday.sh` L1–L7

```bash
#!/bin/bash
# 장중 모니터링 사이클 (KST 12:00, 18:00, 00:00 권장)
# - 뉴스 수집 + LLM 분석 + 비상 매도 체크만 (신규 매매 X)
#
# ⚠️ set -e 를 쓰지 않는다: 뉴스/LLM 단계가 실패해도
#    비상 매도 체크(emergency_exit)는 반드시 실행되어야 하기 때문.

```

