# 오프라인 데모 범위

```bash
python3 -B -m stock_ai_portfolio
python3 -B -m unittest discover -s tests -v
python3 -B tools/check_publication.py
```

저장소 루트에서 실행한다. 설치 명령·자격증명·외부 API·모델 다운로드가 필요 없다. Python 3.10 이상이 필요하며 실제 확인한 버전과 결과는 [검증 보고서](../reports/VALIDATION.md)에 기록한다.

## 입력과 출력

`data/synthetic_scenario.json`은 허구의 종목 식별자와 뉴스 점수·예측 점수·상태 스냅샷을 포함한다. 실제 기사나 계좌에서 익명화한 행이 아닌 **새로 만든 합성 데이터**다. 예측 값은 사람이 정한 예시이며 모델이 만든 값이 아니다. 고정된 `as_of` 시각을 사용한다.

`data/verified_aggregates.json`은 모의 운영 DB의 상태별 집계와 최종 검토 문서의 보고 수치를 담는다. 이 데이터는 합성이 아니며 원시 거래를 제외한 요약이다. 데모는 여기서 문서에 제시된 평균·표준편차·표본 수의 산술만 계산한다.

출력은 JSON이며 stdout으로만 전달된다. 정상 예제에서 미국 `DEMO_US_NEG`는 veto로 제외되고 `DEMO_US_POS`는 +0.05로 순위가 올라간다. 한국 `DEMO_KR_SINGLE`은 뉴스 한 건이라 매수 필터에서는 neutral이지만 단일 대형 악재 조건으로 검토 표시가 생긴다. 금요일에서 토요일로 넘어갈 때 원본 날짜 취소 조건이 참이 되는 것도 출력한다.

## 코드의 출처와 변경

| 모듈 | 과거 구현과의 관계 | 이번 추가·변경 |
|---|---|---|
| `signals.py` | `llm_signals.py`, `emergency_exit.py`의 집계·임계값을 재작성 | pandas·DB·API 분리, 점수 범위 검증, UTC 시각 비교, 미래 제외, 시장 구분, 동률 정렬 |
| `reconciliation.py`의 `legacy_would_cancel` | 전일 open 취소 조건의 최소 재현 | DB 대신 명시적 인자 사용 |
| `reconciliation.py`의 `audit_snapshot` | 원본 문제를 설명하기 위한 신규 개선 예제 | 읽기 전용 경고, pending 구분. 원본에 적용되지 않음 |
| `evaluation.py` | 최종 문서의 SE·t 산식 재작성 | 입력 검증, 정규근사임을 출력 필드에 표시 |
| `__main__.py` | 신규 데모 구성 | 고정 JSON 읽기·JSON stdout 출력 |

원본 신호 helper는 2건 미만이면 집계 점수를 0으로 반환한다. 비상매도는 별도 SQL로 단일 대형 악재를 확인한다. 데모도 이 차이를 유지한다. +0.05 보정으로 1을 넘을 수 있는 값은 `ranking_score`라고 부르며 확률로 표시하지 않는다.

## 재현하지 않는 항목

가격 수집·피처 생성·LightGBM 학습·실제 예측, LLM 뉴스 해석, 외부 인증·잔고 조회, 주문·알림·cron·배포는 실행하지 않는다. 소스 데이터와 독립 평가 구간이 없어 모델 성과 재현을 억지로 구현하지 않았다. 정적 API 발췌는 [reference](../reference/README.md)에서 코드 수준으로 확인한다.

네트워크 차단 테스트와 파일 내용 전후 해시 비교는 이 데모 경로의 동작을 검증한다. 원본의 API 통합이나 EC2 전체 운영을 테스트했다는 뜻은 아니다. 상태 탐지도 입력 스냅샷이 유효하다고 가정하는 제한된 예제다.
