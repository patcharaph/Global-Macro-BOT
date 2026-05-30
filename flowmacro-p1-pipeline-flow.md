# Pipeline Flow (แผนผังการไหลของข้อมูลและกระบวนการ)

**Project (โครงการ):** FlowMacro — Phase 1
**References PRD (อ้างอิง):** global-macro-bot-prd.md v1.4
**References Tech Req (อ้างอิง):** flowmacro-p1-technical-req.md v1.0
**Version:** 1.0
**Author:** Pae (Patchara Phookheaw)
**Date:** 2026-05-30
**Status:** Draft

---

## Overview (ภาพรวม)

Phase 1 มี 2 pipelines หลักที่รัน schedule ต่างกัน และ 1 pipeline สำหรับ backtest:

| Pipeline | ความถี่ | เวลา (Bangkok) | ระยะเวลา |
|----------|---------|----------------|----------|
| P1: Daily Price Pipeline | ทุกวัน | 08:30 | ~3 นาที |
| P2: Weekly Regime Pipeline | ทุกวันศุกร์ | 09:00 | ~8 นาที |
| P3: Backtest Pipeline | Manual / on-demand | - | ~5 นาที |

---

## Pipeline 1: Daily Price Pipeline (P1)

### ภาพรวม Flow

```
GitHub Actions (cron 01:30 UTC)
         │
         ▼
[INIT] generate run_id (UUID) + log pipeline_start
         │
         ▼
[FETCH] yfinance → ดึงราคา 18 tickers
         │
         ├─ SUCCESS ──────────────────────────────────────────────┐
         │                                                        │
         ├─ PARTIAL FAIL (บาง ticker fail)                        │
         │   → log warning + Gmail alert (per ticker)            │
         │   → ดำเนินการต่อด้วย tickers ที่สำเร็จ               │
         │                                                        │
         └─ TOTAL FAIL (ทุก ticker fail)                          │
             → Gmail alert "CRITICAL: all prices failed"         │
             → ไม่บันทึก, exit                                   │
                                                                  ▼
                                                    [CALCULATE] daily indicators
                                                      - SPY vs 200MA distance
                                                      - Copper/Gold ratio (HG=F / GC=F)
                                                      - UUP 20MA trend
                                                      - THB=X rate
                                                         │
                                                         ▼
                                                    [UPDATE] staleness_days
                                                    สำหรับทุก indicator ใน macro_indicators
                                                         │
                                                         ▼
                                                    [SAVE] → Supabase
                                                      - daily_prices (upsert)
                                                      - macro_indicators (update staleness)
                                                         │
                                                         ├─ SUCCESS → log pipeline_success
                                                         │
                                                         └─ FAIL → Gmail alert + log pipeline_failed
```

### Detailed Steps (ขั้นตอนละเอียด)

**Step 1: INIT**

```python
# scripts/run_daily.py
run_id = str(uuid.uuid4())
log = structlog.get_logger().bind(run_id=run_id, run_type="daily")
log.info("pipeline_started")

# บันทึกลง pipeline_runs ทันที (status=running)
db.table("pipeline_runs").insert({
    "run_id": run_id,
    "run_type": "daily",
    "status": "running",
    "started_at": datetime.utcnow().isoformat()
}).execute()
```

**Step 2: FETCH prices**

```python
# src/ingest/price_fetcher.py
TICKERS = [
    "SPY", "QQQ", "IWM",         # US Equity
    "EFA", "EEM", "FXI", "EWJ",  # Intl Equity
    "TLT", "IEF", "HYG",         # Bonds
    "GLD", "USO", "DBC", "SLV",  # Commodities
    "UUP", "FXE", "FXY",         # FX ETF
    "THB=X",                      # THB/USD rate
    "HG=F", "GC=F"               # Copper, Gold futures (for ratio)
]
```

- ดึง 1 วัน (today) สำหรับ daily run
- Retry: 3 ครั้ง, exponential backoff (5s, 10s, 20s)
- Market closed (US holiday, weekend): ไม่ error — log `"market_closed": true`

**Step 3: CALCULATE daily indicators**

```python
# ตัวอย่าง calculation
spy_200ma_distance = (spy_close / spy_200d_ma - 1) * 100  # % above/below
copper_gold_ratio = copper_close / gold_close
uup_20ma_trend = (uup_close / uup_20d_ma - 1) * 100
```

- ใช้ข้อมูลย้อนหลัง 200 วันจาก Supabase สำหรับคำนวณ 200MA
- ถ้าข้อมูลไม่ครบ 200 วัน → ใช้ expanding mean + log warning

**Step 4: UPDATE staleness**

- ทุก indicator ใน `macro_indicators` → `staleness_days += 1`
- Indicators ที่เพิ่งดึงมาวันนี้ → reset `staleness_days = 0`

**Step 5: SAVE + FINISH**

```python
# อัปเดต pipeline_runs
db.table("pipeline_runs").update({
    "status": "success",
    "finished_at": datetime.utcnow().isoformat(),
    "duration_sec": elapsed,
    "log_summary": {"tickers_fetched": N, "warnings": [...]}
}).eq("run_id", run_id).execute()
```

### Error Handling (การจัดการ Error)

| Error | Action | Alert? |
|-------|--------|--------|
| yfinance timeout (1 ticker) | retry 3x → ใช้ last known value | ✅ Gmail |
| yfinance fail (> 5 tickers) | ดำเนินการต่อ + mark stale | ✅ Gmail |
| yfinance fail (ทุก ticker) | exit pipeline | ✅ Gmail CRITICAL |
| Supabase write fail | retry 2x → exit | ✅ Gmail |
| Indicator calculation error | skip indicator + log | ✅ Gmail (ถ้า Tier 1) |

---

## Pipeline 2: Weekly Regime Pipeline (P2)

### ภาพรวม Flow

```
GitHub Actions (cron 02:00 UTC Friday)
         │
         ▼
[INIT] generate run_id + log pipeline_start
         │
         ▼
[FETCH FRED] ดึง 8 FRED series
         │
         ├─ SUCCESS (ทุกตัว) ────────────────────────────────────┐
         │                                                        │
         ├─ PARTIAL FAIL (บาง indicator fail)                     │
         │   → carry forward last known value                    │
         │   → set staleness_days จริง                           │
         │   → Gmail alert ถ้า Tier 1 fail                        │
         │                                                        │
         └─ TOTAL FAIL                                            │
             → Gmail alert CRITICAL, exit                         │
                                                                  ▼
                                                    [LOAD MARKET DATA] จาก Supabase
                                                    (SPY 200MA, Copper/Gold, UUP 20MA)
                                                    ← คำนวณไว้แล้วจาก daily run
                                                         │
                                                         ▼
                                                    [NORMALIZE] Percentile Rank
                                                    ทุก indicator → rolling 5Y window
                                                         │
                                                         ▼
                                                    [SCORE] Axis Scoring
                                                    growth_score + inflation_score
                                                    + leading_score (Tier 1 only)
                                                         │
                                                         ▼
                                                    [CLASSIFY] Regime + Confidence
                                                    confidence = min(growth_conf, inflation_conf)
                                                    if confidence < 40% → TRANSITIONING
                                                         │
                                                         ▼
                                                    [COMPARE] vs Previous Regime
                                                    regime_changed = (new != previous)
                                                         │
                                                         ▼
                                                    [SAVE] → Supabase
                                                    regime_history + macro_indicators
                                                         │
                                                         ▼
                                                    [NOTIFY] ส่ง Gmail alert
                                                    ถ้า regime เปลี่ยน หรือ confidence < 60%
                                                         │
                                                         ▼
                                                    [FINISH] log pipeline_success
```

### Detailed Steps (ขั้นตอนละเอียด)

**Step 2: FETCH FRED**

```python
# src/ingest/macro_fetcher.py
FRED_SERIES = {
    # Tier 1 - Growth
    "T10Y2Y":          {"name": "Yield Curve 10Y-2Y",  "tier": 1, "axis": "growth",    "inverse": False},
    "BAMLH0A0HYM2":    {"name": "HY Credit Spread",    "tier": 1, "axis": "growth",    "inverse": True},
    "USSLIND":         {"name": "LEI",                 "tier": 1, "axis": "growth",    "inverse": False},
    # Tier 1 - Inflation
    "T5YIE":           {"name": "5Y Breakeven",        "tier": 1, "axis": "inflation", "inverse": False},
    # Tier 2 - Growth (market-based - ดึงจาก yfinance แล้ว)
    # "copper_gold_ratio", "spy_200ma", "uup_20ma" → ใช้จาก daily_prices
    # Tier 2 - Growth (FRED)
    "MANEMP":          {"name": "Mfg Employment",      "tier": 2, "axis": "growth",    "inverse": False},
    # Tier 3 - Growth
    "UNRATE":          {"name": "Unemployment",        "tier": 3, "axis": "growth",    "inverse": True},
    "A191RL1Q225SBEA": {"name": "Real GDP Growth",     "tier": 3, "axis": "growth",    "inverse": False},
    # Tier 3 - Inflation
    "CPIAUCSL":        {"name": "CPI YoY",             "tier": 3, "axis": "inflation", "inverse": False},
}
```

**Step 4: NORMALIZE — Percentile Rank**

```python
# src/signals/percentile.py

def calculate_percentile_rank(
    series: pd.Series,
    window: int = 260  # 5 ปี = 260 สัปดาห์
) -> pd.Series:
    """
    rolling percentile rank: ค่าปัจจุบันอยู่ที่ percentile เท่าไหร่ใน 5 ปีที่ผ่านมา
    ถ้าข้อมูลน้อยกว่า window → expanding window (ช่วง backtest ปีแรก)
    """
    def rank_scalar(window_values):
        current = window_values.iloc[-1]
        return (window_values < current).sum() / len(window_values) * 100

    return series.rolling(window=window, min_periods=52).apply(
        rank_scalar, raw=False
    )
```

**Step 5: SCORE — Axis Scoring**

```python
# src/signals/scorer.py

# Tier weights (เป็น relative weight ภายใน axis)
TIER_WEIGHTS = {1: 0.50, 2: 0.30, 3: 0.20}

def compute_growth_score(percentile_ranks: dict) -> float:
    """
    growth indicators พร้อม weights:
    Tier 1: yield_curve (inverse handled), credit_spread (inverse), lei
    Tier 2: ism_pmi_proxy, copper_gold_ratio, spy_200ma
    Tier 3: unemployment (inverse), real_gdp
    """
    growth_indicators = [
        ("T10Y2Y",          1, False),
        ("BAMLH0A0HYM2",    1, True),   # inverse
        ("USSLIND",         1, False),
        ("MANEMP",          2, False),
        ("copper_gold_ratio",2, False),
        ("spy_200ma",       2, False),
        ("UNRATE",          3, True),    # inverse
        ("A191RL1Q225SBEA", 3, False),
    ]
    return _weighted_score(percentile_ranks, growth_indicators)

def compute_inflation_score(percentile_ranks: dict) -> float:
    inflation_indicators = [
        ("T5YIE",    1, False),
        ("uup_20ma", 2, True),   # inverse: USD แข็ง = imported inflation ต่ำ
        ("CPIAUCSL", 3, False),
    ]
    return _weighted_score(percentile_ranks, inflation_indicators)

def _weighted_score(ranks: dict, indicators: list) -> float:
    # normalize weights per tier (แต่ละ tier รวมกัน = tier_weight)
    tier_totals = {}
    for _, tier, _ in indicators:
        tier_totals[tier] = tier_totals.get(tier, 0) + 1

    total_weight = 0
    weighted_sum = 0
    for indicator_id, tier, inverse in indicators:
        rank = ranks.get(indicator_id)
        if rank is None:
            continue  # skip missing (stale carry-forward ไม่มีผลต่อ weight)
        weight = TIER_WEIGHTS[tier] / tier_totals[tier]
        value = (100 - rank) if inverse else rank
        weighted_sum += value * weight
        total_weight += weight

    return (weighted_sum / total_weight) if total_weight > 0 else 50.0
```

**Step 6: CLASSIFY — Regime + Confidence**

```python
# src/signals/regime_classifier.py

from dataclasses import dataclass
from enum import Enum

class Regime(str, Enum):
    GOLDILOCKS    = "GOLDILOCKS"
    REFLATION     = "REFLATION"
    STAGFLATION   = "STAGFLATION"
    DEFLATION     = "DEFLATION"
    TRANSITIONING = "TRANSITIONING"

ENTRY_THRESHOLD = 40.0  # confidence ≥ 40% → classify
EXIT_THRESHOLD  = 50.0  # hysteresis: ออกจาก TRANSITIONING เมื่อ confidence ≥ 50%

@dataclass
class RegimeResult:
    regime: Regime
    confidence: float
    growth_score: float
    inflation_score: float
    leading_score: float
    staleness_flags: dict

def classify_regime(
    growth_score: float,
    inflation_score: float,
    leading_score: float,
    staleness_flags: dict,
    previous_regime: Regime | None = None
) -> RegimeResult:

    growth_conf    = 2 * abs(growth_score - 50)
    inflation_conf = 2 * abs(inflation_score - 50)
    confidence     = min(growth_conf, inflation_conf)

    # Hysteresis: ถ้า previous = TRANSITIONING ต้องได้ ≥ 50% ถึงจะออก
    threshold = EXIT_THRESHOLD if previous_regime == Regime.TRANSITIONING else ENTRY_THRESHOLD

    if confidence < threshold:
        regime = Regime.TRANSITIONING
    elif growth_score > 50 and inflation_score > 50:
        regime = Regime.REFLATION
    elif growth_score > 50 and inflation_score <= 50:
        regime = Regime.GOLDILOCKS
    elif growth_score <= 50 and inflation_score > 50:
        regime = Regime.STAGFLATION
    else:
        regime = Regime.DEFLATION

    return RegimeResult(
        regime=regime,
        confidence=round(confidence, 2),
        growth_score=round(growth_score, 2),
        inflation_score=round(inflation_score, 2),
        leading_score=round(leading_score, 2),
        staleness_flags=staleness_flags
    )
```

**Step 8: NOTIFY — Gmail Alert Logic**

```python
# src/notify/gmail_notifier.py

def should_notify(result: RegimeResult, previous_regime: str) -> tuple[bool, str]:
    if result.regime.value != previous_regime:
        reason = f"regime_changed: {previous_regime} → {result.regime.value}"
        return True, reason
    if result.confidence < 60.0:
        reason = f"low_confidence: {result.confidence}%"
        return True, reason
    return False, ""

def send_gmail_alert(subject: str, body: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("GMAIL_SENDER")
    msg["To"] = os.getenv("GMAIL_RECIPIENT")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(os.getenv("GMAIL_SENDER"), os.getenv("GMAIL_APP_PASSWORD"))
        smtp.send_message(msg)
    return True
```

### Error Handling (การจัดการ Error)

| Step | Error | Action | Alert? |
|------|-------|--------|--------|
| FETCH FRED | API timeout | retry 3x backoff | - |
| FETCH FRED | Tier 1 indicator fail | carry forward + flag stale | ✅ Gmail |
| FETCH FRED | ทุก indicator fail | exit pipeline | ✅ Gmail CRITICAL |
| NORMALIZE | ข้อมูลน้อยกว่า 52 สัปดาห์ | expanding window + log warning | - |
| SCORE | indicator missing | skip + adjust weights | log |
| SAVE | Supabase write fail | retry 2x → exit | ✅ Gmail |
| NOTIFY | Gmail SMTP fail | log error + ไม่ crash pipeline | log |

---

## Pipeline 3: Backtest Pipeline (P3)

### ภาพรวม Flow

```
Manual trigger (local หรือ GitHub Actions workflow_dispatch)
         │
         ▼
[INIT] generate run_id + log backtest_start
         │
         ▼
[LOAD] ดึงราคา ETF 20 ปีจาก Supabase
       (หรือ yfinance โดยตรงสำหรับ initial run)
         │
         ▼
[LOAD] ดึง macro indicators 20 ปีจาก Supabase
         │
         ▼
[REPLAY] คำนวณ regime history ย้อนหลัง
         - ทุกสัปดาห์ (วันศุกร์) ย้อนไป 2005
         - ใช้ algorithm เดียวกับ P2 (reproducibility)
         - ⚠️ DBC/SLV ก่อน 2006 → ใช้ GLD+USO แทน
         │
         ▼
[BACKTEST] vectorbt walk-forward
         - Train: 10 ปี, Test: 5 ปี, Roll: 1 ปี
         - Transaction costs: bid-ask 0.05% + premium 0.1% + $1 commission
         - Equal weight allocation ต่อ regime
         - Cash buffer 20% ทุก regime (TRANSITIONING 50%)
         │
         ▼
[BENCHMARK] คำนวณ 60/40 (SPY 60% + TLT 40%)
         - Rebalance รายไตรมาส
         - Same transaction costs
         │
         ▼
[METRICS] คำนวณ performance metrics
         FlowMacro + 60/40 benchmark:
         - Sharpe Ratio, Sortino Ratio
         - Max Drawdown, Calmar Ratio
         - Annual Return, Win Rate
         - Out-of-sample period clearly labeled
         │
         ▼
[SAVE] บันทึกลง backtest_runs
         │
         ▼
[DISPLAY] แสดงผลใน Streamlit dashboard
         - Equity curve chart
         - Drawdown chart
         - Metrics comparison table
```

### Walk-Forward Configuration

```python
# src/backtest/engine.py

WALK_FORWARD_CONFIG = {
    "train_years": 10,
    "test_years": 5,
    "roll_years": 1,
    "start_year": 2005,
    "end_year": 2025,
}

# สร้าง periods อัตโนมัติ:
# Period 1: Train 2005-2014, Test 2015-2019
# Period 2: Train 2006-2015, Test 2016-2020
# Period 3: Train 2007-2016, Test 2017-2021
# Period 4: Train 2008-2017, Test 2018-2022
# Period 5: Train 2009-2018, Test 2019-2023
```

### Transaction Cost Model

```python
# src/backtest/engine.py

TRANSACTION_COSTS = {
    "bid_ask_spread_pct": 0.05 / 100,    # 0.05% per trade
    "etf_premium_discount_pct": 0.10 / 100, # ±0.10% (use 0.10% conservatively)
    "commission_usd": 1.0,               # $1 per trade
}

def apply_transaction_costs(portfolio_value: float, n_trades: int) -> float:
    """คำนวณ total transaction cost สำหรับ 1 rebalancing"""
    trade_value = portfolio_value * 0.8  # 80% ของพอร์ตที่ actively managed
    cost_pct = TRANSACTION_COSTS["bid_ask_spread_pct"] + TRANSACTION_COSTS["etf_premium_discount_pct"]
    cost_usd = trade_value * cost_pct + (n_trades * TRANSACTION_COSTS["commission_usd"])
    return cost_usd
```

---

## Data Flow Diagram (แผนผังการไหลของข้อมูล)

```
DATA SOURCES                    SUPABASE TABLES                 OUTPUTS
─────────────────               ─────────────────               ─────────────────
yfinance (daily)    ──────────► daily_prices           ──────► Streamlit
  ETF prices                                                     - Equity curve
  THB=X                         macro_indicators        ──────► - Regime panel
  HG=F, GC=F        ──────────► (staleness_days)
                                                                 Gmail
FRED API (weekly)   ──────────► macro_indicators        ──────► - Regime change
  T10Y2Y                        (FRED values)                   - Data failure
  BAMLH0A0HYM2
  T5YIE              Pipeline   regime_history          ──────► Streamlit
  USSLIND            Process ►  (weekly output)                  - Regime history
  MANEMP             (P2)                                        - Confidence
  UNRATE                        backtest_runs           ──────► Streamlit
  CPIAUCSL           Backtest ► (performance)                    - Backtest chart
  A191RL1Q225SBEA    (P3)
                                pipeline_runs           ──────► Streamlit
                                (job logs)                       - Health panel
```

---

## Streamlit Dashboard Flow (การไหลของ Dashboard)

```
User เปิด browser → localhost:8501
         │
         ▼
app.py → เชื่อมต่อ Supabase (connection pool)
         │
         ├── Page 1: Regime (1_regime.py)
         │   ├── Query: regime_history ORDER BY date DESC LIMIT 1
         │   ├── Query: macro_indicators (latest per indicator)
         │   ├── Display:
         │   │   ├── [Hero] current_regime (ตัวใหญ่ + สี)
         │   │   ├── [Metrics] confidence, growth_score, inflation_score
         │   │   ├── [Table] indicators + percentile + staleness flag
         │   │   ├── [Table] allocation suggestion (read-only)
         │   │   └── [FX] USD value + THB equivalent
         │   └── Refresh: ทุก 1 ชั่วโมง (Streamlit cache TTL)
         │
         ├── Page 2: Backtest (2_backtest.py)
         │   ├── Query: backtest_runs ORDER BY run_date DESC LIMIT 1
         │   ├── Query: daily_prices สำหรับ equity curve
         │   ├── Display:
         │   │   ├── [Metrics] FlowMacro vs 60/40 (Sharpe, MaxDD, Return)
         │   │   ├── [Chart] Equity curve (Plotly line chart)
         │   │   ├── [Chart] Drawdown chart
         │   │   └── [Warning] ถ้า Sharpe < 1.0 หรือ return < benchmark
         │   └── Refresh: manual (ไม่ auto-refresh)
         │
         └── Page 3: Health (3_health.py)
             ├── Query: pipeline_runs ORDER BY started_at DESC LIMIT 10
             ├── Display:
             │   ├── [Status] data source health (yfinance, FRED, Supabase, Gmail)
             │   ├── [Table] last 10 runs (run_id, type, status, duration)
             │   └── [Detail] คลิก run_id → แสดง log_summary JSON
             └── Refresh: ทุก 5 นาที
```

---

## Error Recovery Playbook (คู่มือการกู้คืน Error)

### Scenario A: yfinance rate limited

```
Symptom: daily job fail, Gmail alert "yfinance fetch failed"
Diagnosis: ดู GitHub Actions log → "429 Too Many Requests"
Recovery:
  1. รอ 1 ชั่วโมง (rate limit reset)
  2. trigger daily job ด้วย workflow_dispatch
  3. ถ้ายัง fail → ดึงข้อมูลด้วย manual script บน local แล้ว push ผ่าน script
Timeline: < 2 ชั่วโมง
```

### Scenario B: FRED API key expired

```
Symptom: weekly job fail, Gmail alert "FRED fetch failed T1"
Diagnosis: ดู log → "403 Forbidden" หรือ "Invalid API key"
Recovery:
  1. ไปที่ fred.stlouisfed.org → regenerate API key
  2. อัปเดต GitHub Secrets (FRED_API_KEY)
  3. trigger weekly job ด้วย workflow_dispatch
Timeline: < 30 นาที
```

### Scenario C: Supabase connection fail

```
Symptom: job fail, ไม่มีข้อมูลใน dashboard
Diagnosis: ดู log → "Connection refused" หรือ Supabase dashboard
Recovery:
  1. ตรวจสอบ Supabase status page (status.supabase.com)
  2. ถ้า Supabase down → รอ (ไม่มีอะไรทำได้)
  3. ถ้า connection string ผิด → ตรวจ GitHub Secrets
  4. trigger job ใหม่เมื่อ Supabase กลับมา
Timeline: ขึ้นกับ Supabase uptime
```

### Scenario D: Regime stuck in TRANSITIONING นานกว่า 8 สัปดาห์

```
Symptom: regime = TRANSITIONING ติดต่อกัน > 8 สัปดาห์
Diagnosis:
  1. ดู growth_score + inflation_score ใน dashboard
  2. ตรวจ staleness flags — Tier 1 indicator stale ไหม?
  3. ดู leading_score แยก — trend ชัดขึ้นไหม?
Action:
  - ไม่เปิด position ใหม่ (ตาม protocol)
  - Review indicator data quality
  - ถ้า stale indicator เป็นสาเหตุ → แก้ data fetch ก่อน
  - ไม่แก้ threshold โดยตรงในช่วงที่ตลาดผันผวน
```

---

## Logging Standards (มาตรฐาน Logging)

### ทุก pipeline stage ต้อง log ตามนี้:

```python
# Stage start
log.info("stage_started", stage="fetch_fred", run_id=run_id)

# Stage success
log.info("stage_completed", stage="fetch_fred",
    indicators_fetched=8,
    duration_sec=2.3,
    run_id=run_id
)

# Stage warning (partial fail)
log.warning("indicator_stale", stage="fetch_fred",
    indicator_id="USSLIND",
    tier=1,
    staleness_days=35,
    using_value="carry_forward",
    run_id=run_id
)

# Stage error
log.error("stage_failed", stage="fetch_fred",
    error_type="HTTPError",
    error_msg="429 Too Many Requests",
    indicator_id="T10Y2Y",
    retry_count=3,
    suggested_fix="Rate limit hit — reduce fetch frequency",
    run_id=run_id
)

# Signal calculation log (ทุก signal ต้อง log นี้)
log.info("signal_calculated",
    indicator_id="T10Y2Y",
    input_value=0.42,
    percentile_rank=73.5,
    window_size=260,
    staleness_days=0,
    run_id=run_id
)

# Regime output log
log.info("regime_classified",
    current_regime="GOLDILOCKS",
    regime_confidence=72.5,
    growth_score=68.3,
    inflation_score=32.1,
    leading_score=71.0,
    regime_changed=False,
    run_id=run_id
)
```

---

## Appendix: Indicator Reference (ข้อมูลอ้างอิง Indicators)

| Indicator | FRED/yfinance ID | Axis | Tier | Inverse | Update | Staleness Alert |
|-----------|-----------------|------|------|---------|--------|----------------|
| Yield curve (10Y-2Y) | `T10Y2Y` | Growth | T1 | No | Daily | > 7 วัน |
| HY Credit spread | `BAMLH0A0HYM2` | Growth | T1 | Yes | Daily | > 7 วัน |
| LEI | `USSLIND` | Growth | T1 | No | Monthly | > 45 วัน |
| 5Y Breakeven inflation | `T5YIE` | Inflation | T1 | No | Daily | > 7 วัน |
| ISM/Mfg proxy | `MANEMP` | Growth | T2 | No | Monthly | > 45 วัน |
| Copper/Gold ratio | `HG=F`/`GC=F` | Growth | T2 | No | Daily | > 3 วัน |
| SPY vs 200MA | `SPY` | Growth | T2 | No | Daily | > 3 วัน |
| DXY trend (UUP 20MA) | `UUP` | Inflation | T2 | Yes | Daily | > 3 วัน |
| Unemployment | `UNRATE` | Growth | T3 | Yes | Monthly | > 45 วัน |
| Real GDP | `A191RL1Q225SBEA` | Growth | T3 | No | Quarterly | > 100 วัน |
| CPI YoY | `CPIAUCSL` | Inflation | T3 | No | Monthly | > 45 วัน |

---

## Revision History (ประวัติการแก้ไข)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-30 | Pae | Initial draft — P1 Daily, P2 Weekly, P3 Backtest pipelines ครบทุก step พร้อม error recovery playbook |
