# Technical Requirements & Architecture Decision Records (ข้อกำหนดทางเทคนิคและการตัดสินใจสถาปัตยกรรม)

**Project (โครงการ):** FlowMacro — Phase 1
**References PRD (อ้างอิง):** global-macro-bot-prd.md v1.4
**References User Stories:** flowmacro-p1-user-stories.md v1.0
**Version:** 1.0
**Author:** Pae (Patchara Phookheaw)
**Date:** 2026-05-30
**Status:** Draft
**Last validated:** 2026-05-30

---

## 1. System Architecture (สถาปัตยกรรมระบบ)

### 1.1 Component Diagram (ภาพรวม components)

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions (Scheduler)                                     │
│  ├── daily_job.yml   → 01:30 UTC (08:30 BKK)                   │
│  └── weekly_job.yml  → 02:00 UTC Friday (09:00 BKK)            │
└──────────────────────┬──────────────────────────────────────────┘
                       │ triggers
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Python Pipeline (src/)                                         │
│  ├── ingest/                                                    │
│  │   ├── price_fetcher.py     ← yfinance                       │
│  │   └── macro_fetcher.py     ← FRED API                       │
│  ├── signals/                                                   │
│  │   ├── percentile.py        ← rolling 5Y rank                │
│  │   ├── scorer.py            ← growth/inflation scores         │
│  │   └── regime_classifier.py ← confidence + quadrant          │
│  ├── backtest/                                                  │
│  │   ├── engine.py            ← vectorbt walk-forward           │
│  │   └── benchmark.py        ← 60/40 comparison                │
│  └── alerts/                                                    │
│      └── gmail.py             ← Gmail SMTP alert               │
└──────────────────────┬──────────────────────────────────────────┘
                       │ read/write
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Supabase (Postgres)                                            │
│  ├── daily_prices              (ETF OHLCV)                      │
│  ├── macro_indicators          (FRED + market data)             │
│  ├── regime_history            (weekly regime output)           │
│  ├── backtest_runs             (backtest results)               │
│  └── pipeline_runs             (job run log)                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │ read
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit Dashboard (dashboard/)                               │
│  ├── pages/1_regime.py         ← regime + scores + flags       │
│  ├── pages/2_backtest.py       ← equity curve + metrics        │
│  └── pages/3_health.py         ← run history + data status     │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Project Structure (โครงสร้างไฟล์)

```
flowmacro/
├── .env                          ← secrets (gitignored)
├── .env.example                  ← template สำหรับ setup
├── .github/
│   └── workflows/
│       ├── daily_job.yml
│       └── weekly_job.yml
├── src/
│   ├── __init__.py
│   ├── config.py                 ← load .env, constants
│   ├── db.py                     ← Supabase client singleton
│   ├── logger.py                 ← structlog setup
│   ├── ingest/
│   │   ├── price_fetcher.py
│   │   └── macro_fetcher.py
│   ├── signals/
│   │   ├── percentile.py
│   │   ├── scorer.py
│   │   └── regime_classifier.py
│   ├── backtest/
│   │   ├── engine.py
│   │   └── benchmark.py
│   └── alerts/
│       └── gmail.py
├── dashboard/
│   ├── app.py                    ← Streamlit entrypoint
│   └── pages/
│       ├── 1_regime.py
│       ├── 2_backtest.py
│       └── 3_health.py
├── scripts/
│   ├── run_daily.py              ← entrypoint สำหรับ daily job
│   └── run_weekly.py             ← entrypoint สำหรับ weekly job
├── tests/
│   ├── test_percentile.py
│   ├── test_regime_classifier.py
│   └── test_scorer.py
├── requirements.txt
└── README.md
```

---

## 2. Database Schema (โครงสร้างฐานข้อมูล)

### 2.1 Table: `daily_prices`

```sql
CREATE TABLE daily_prices (
  id           BIGSERIAL PRIMARY KEY,
  run_id       UUID NOT NULL,
  ticker       VARCHAR(10) NOT NULL,
  date         DATE NOT NULL,
  open         NUMERIC(12,4),
  high         NUMERIC(12,4),
  low          NUMERIC(12,4),
  close        NUMERIC(12,4) NOT NULL,
  adj_close    NUMERIC(12,4) NOT NULL,
  volume       BIGINT,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (ticker, date)
);
CREATE INDEX idx_daily_prices_ticker_date ON daily_prices (ticker, date DESC);
```

### 2.2 Table: `macro_indicators`

```sql
CREATE TABLE macro_indicators (
  id             BIGSERIAL PRIMARY KEY,
  run_id         UUID NOT NULL,
  indicator_id   VARCHAR(30) NOT NULL,    -- เช่น 'T10Y2Y', 'BAMLH0A0HYM2'
  indicator_name VARCHAR(100) NOT NULL,
  date           DATE NOT NULL,
  value          NUMERIC(16,6) NOT NULL,
  source         VARCHAR(20) NOT NULL,    -- 'FRED' หรือ 'yfinance'
  tier           SMALLINT NOT NULL,       -- 1, 2, 3
  axis           VARCHAR(10) NOT NULL,    -- 'growth' หรือ 'inflation'
  is_inverse     BOOLEAN NOT NULL DEFAULT FALSE,
  staleness_days SMALLINT NOT NULL DEFAULT 0,
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (indicator_id, date)
);
CREATE INDEX idx_macro_indicators_id_date ON macro_indicators (indicator_id, date DESC);
```

### 2.3 Table: `regime_history`

```sql
CREATE TABLE regime_history (
  id                BIGSERIAL PRIMARY KEY,
  run_id            UUID NOT NULL UNIQUE,
  date              DATE NOT NULL,
  current_regime    VARCHAR(20) NOT NULL,  -- GOLDILOCKS/REFLATION/STAGFLATION/DEFLATION/TRANSITIONING
  regime_confidence NUMERIC(5,2) NOT NULL, -- 0.00-100.00
  growth_score      NUMERIC(5,2) NOT NULL,
  inflation_score   NUMERIC(5,2) NOT NULL,
  leading_score     NUMERIC(5,2),
  staleness_flags   JSONB NOT NULL DEFAULT '{}',
  previous_regime   VARCHAR(20),
  regime_changed    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_regime_history_date ON regime_history (date DESC);
```

### 2.4 Table: `backtest_runs`

```sql
CREATE TABLE backtest_runs (
  id                  BIGSERIAL PRIMARY KEY,
  run_id              UUID NOT NULL UNIQUE,
  run_date            DATE NOT NULL,
  period_start        DATE NOT NULL,
  period_end          DATE NOT NULL,
  sharpe_ratio        NUMERIC(8,4),
  max_drawdown        NUMERIC(8,4),   -- เป็น % เช่น -15.23
  annual_return       NUMERIC(8,4),   -- เป็น % เช่น 12.45
  calmar_ratio        NUMERIC(8,4),
  win_rate            NUMERIC(5,2),   -- เป็น % เช่น 58.30
  benchmark_sharpe    NUMERIC(8,4),
  benchmark_return    NUMERIC(8,4),
  outperforms_benchmark BOOLEAN,
  vectorbt_version    VARCHAR(20),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 2.5 Table: `pipeline_runs`

```sql
CREATE TABLE pipeline_runs (
  id           BIGSERIAL PRIMARY KEY,
  run_id       UUID NOT NULL UNIQUE,
  run_type     VARCHAR(20) NOT NULL,   -- 'daily' หรือ 'weekly'
  status       VARCHAR(20) NOT NULL,   -- 'running', 'success', 'failed'
  started_at   TIMESTAMPTZ NOT NULL,
  finished_at  TIMESTAMPTZ,
  duration_sec NUMERIC(8,2),
  error_msg    TEXT,
  log_summary  JSONB DEFAULT '{}',    -- { "steps": [...], "warnings": [...] }
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pipeline_runs_started ON pipeline_runs (started_at DESC);
```

---

## 3. Architecture Decision Records (ADR)

### ADR-001: ใช้ vectorbt สำหรับ backtest engine

**Status:** Accepted
**Date:** 2026-05-30

**Context (บริบท):**
ต้องการ backtest engine ที่รัน walk-forward 20 ปีได้รวดเร็วบน position trading (weekly signals) และ support Python 3.12+

**Decision (การตัดสินใจ):**
ใช้ `vectorbt` (latest stable)

**Rationale (เหตุผล):**
- Vectorized operations → 20 ปีรันได้ใน < 30 วินาที (เทียบ backtrader ที่ใช้ loop)
- Active maintenance ณ 2025 (backtrader หยุด active development ปี 2023)
- รองรับ walk-forward built-in ผ่าน `vbt.Portfolio.from_signals()` + rolling windows
- Python 3.12+ compatible

**Rejected alternatives (ทางเลือกที่ปฏิเสธ):**
- `backtrader`: หยุด development 2023, event-driven (ช้ากว่า 10-50x)
- `zipline-reloaded`: ยังมี dependency issues กับ Python 3.12+
- Custom numpy: ใช้เวลา build นาน, maintenance สูง

**Consequences (ผลที่ตามมา):**
- ต้อง learn vectorbt API (learning curve ~3 วัน)
- Backtest output format ต่างจาก traditional event-driven — ต้องระวังการ interpret results

---

### ADR-002: ใช้ Supabase แทน local database

**Status:** Accepted
**Date:** 2026-05-30

**Context:**
ต้องการ database ที่ GitHub Actions เข้าถึงได้ (cloud) และ Streamlit dashboard อ่านได้ โดยมี budget < $100/เดือน

**Decision:**
ใช้ Supabase (free tier: 500MB storage, 2GB bandwidth/เดือน)

**Rationale:**
- Free tier เพียงพอสำหรับ Phase 1 (ประมาณ 50MB/ปีสำหรับ price + macro data)
- มี Postgres client ใช้ได้ทุก Python version
- มี dashboard สำหรับ debug data โดยตรง
- No cold start (ต่างจาก serverless DB)

**Rejected alternatives:**
- DuckDB (local): GitHub Actions ไม่มี persistent storage
- SQLite: ไม่รองรับ concurrent read จาก Streamlit + pipeline พร้อมกัน
- TimescaleDB (cloud): over-engineered, expensive

**Consequences:**
- Data อยู่บน cloud → ต้อง secure connection string ใน GitHub Secrets
- Free tier limit: ถ้า data > 500MB ต้อง upgrade ($25/เดือน)

---

### ADR-003: ใช้ percentile rank (rolling 5Y) แทน Z-score

**Status:** Accepted
**Date:** 2026-05-30

**Context:**
ต้องการ normalize indicators ที่มี scale ต่างกัน (เช่น yield curve -2% ถึง +3%, CPI 0% ถึง 9%) ให้เปรียบเทียบกันได้

**Decision:**
ใช้ rolling percentile rank (5-year window, 260 weeks)

**Rationale:**
- Robust ต่อ outliers — COVID crash (2020) หรือ inflation spike (2022) ไม่ทำให้ Z-score distort
- Intuitive: percentile 80 หมายถึง "สูงกว่า 80% ของช่วง 5 ปีที่ผ่านมา" — อ่านง่าย
- Bounded 0-100 ทำให้ weight calculation predictable (ต่างจาก Z-score ที่ unbounded)
- Bridgewater ใช้ approach คล้ายกันใน All Weather framework

**Rejected alternatives:**
- Z-score: ไม่ bounded, outlier-sensitive
- Min-max normalization: ไม่ rolling → ค่าขึ้นกับ historical min/max ที่อาจ outdated

**Consequences:**
- ต้องมีข้อมูลอย่างน้อย 1 ปีก่อนจะ calculate percentile ได้ → ช่วง backtest ปี 2005 ใช้ expanding window
- ⚠️ ASSUMPTION: rolling 5Y (260 weeks) เหมาะสมสำหรับ position trading — อาจต้องทดสอบ 3Y และ 7Y ใน backtest

---

### ADR-004: GitHub Actions เป็น scheduler แทน dedicated cron server

**Status:** Accepted
**Date:** 2026-05-30

**Context:**
ต้องการ run daily และ weekly jobs อัตโนมัติโดยไม่มี cost

**Decision:**
ใช้ GitHub Actions cron triggers

**Rationale:**
- Free สำหรับ public repo (2,000 minutes/เดือน เพียงพอ: 31 วัน × 5 นาที = 155 minutes/เดือน)
- Version-controlled workflow — audit trail ทุก run
- Secrets management built-in (SUPABASE_URL, FRED_API_KEY, GMAIL_SENDER, GMAIL_APP_PASSWORD)
- ไม่มี infrastructure ให้ maintain

**Known limitation:**
- GitHub Actions อาจ pause inactive repos อัตโนมัติหลัง 60 วัน → แก้ด้วย heartbeat commit script ทุก 50 วัน
- Cron time ไม่แม่นยำ 100% (อาจ delay 0-5 นาที) → acceptable สำหรับ daily/weekly job

**Rejected alternatives:**
- AWS Lambda + EventBridge: vendor lock-in, มี cold start, cost
- Railway/Render cron: paid tier ถึงจะ reliable
- Local machine: ไม่ available 24/7

---

### ADR-005: ใช้ structlog สำหรับ structured logging

**Status:** Accepted
**Date:** 2026-05-30

**Context:**
ต้องการ logging ที่ trace ได้ด้วย `run_id` และ debug pipeline ได้ง่ายใน GitHub Actions logs

**Decision:**
ใช้ `structlog` กับ JSON output format

**Rationale:**
- JSON format → copy-paste log ไป parse ใน Supabase หรือ query ได้ทันที
- Bind `run_id` ใน context → ทุก log line มี `run_id` โดยอัตโนมัติ
- Better กว่า `logging` standard library ใน terms of structured output

**Log format ที่กำหนด:**
```json
{
  "timestamp": "2026-05-30T08:30:15.123Z",
  "level": "info",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_type": "weekly",
  "module": "regime_classifier",
  "event": "regime_classified",
  "current_regime": "GOLDILOCKS",
  "confidence": 72.5,
  "growth_score": 68.3,
  "inflation_score": 32.1
}
```

**Error log format ที่กำหนด:**
```json
{
  "timestamp": "...",
  "level": "error",
  "run_id": "...",
  "module": "macro_fetcher",
  "event": "fred_fetch_failed",
  "indicator_id": "T10Y2Y",
  "error_type": "HTTPError",
  "error_msg": "429 Too Many Requests",
  "retry_count": 3,
  "suggested_fix": "FRED rate limit hit — reduce fetch frequency or upgrade API key"
}
```

---

## 4. API Integrations (การเชื่อมต่อ API)

### 4.1 yfinance

```python
# ข้อกำหนดการใช้งาน
import yfinance as yf

# Fetch single ticker
ticker = yf.Ticker("SPY")
df = ticker.history(start="2005-01-01", end="2025-12-31", auto_adjust=True)

# Fetch multiple tickers (efficient)
tickers = yf.download(
    tickers=["SPY", "QQQ", "GLD"],
    start="2005-01-01",
    interval="1d",
    auto_adjust=True,
    group_by="ticker"
)
```

**Rate limits:** ไม่มี official limit แต่ > 100 requests/นาที อาจถูก block
**Retry strategy:** 3 retries, exponential backoff (5s, 10s, 20s)
**Staleness threshold:** price data — stale ถ้า > 1 วัน (ยกเว้น weekend/holiday)

### 4.2 FRED API

```python
# ข้อกำหนดการใช้งาน
from fredapi import Fred

fred = Fred(api_key=os.getenv("FRED_API_KEY"))

# Fetch single series
df = fred.get_series(
    series_id="T10Y2Y",
    observation_start="2005-01-01",
    observation_end="2025-12-31"
)
```

**FRED Series IDs ที่ใช้:**

| Series ID | Indicator | Axis | Tier | Update Frequency |
|-----------|-----------|------|------|-----------------|
| `T10Y2Y` | Yield curve (10Y-2Y) | Growth | T1 | Daily |
| `BAMLH0A0HYM2` | HY credit spread | Growth | T1 | Daily |
| `T5YIE` | 5Y breakeven inflation | Inflation | T1 | Daily |
| `USSLIND` | Conference Board LEI | Growth | T1 | Monthly |
| `MANEMP` | Manufacturing employment (ISM proxy) | Growth | T2 | Monthly |
| `UNRATE` | Unemployment rate | Growth | T3 | Monthly |
| `CPIAUCSL` | CPI All Urban | Inflation | T3 | Monthly |
| `A191RL1Q225SBEA` | Real GDP growth | Growth | T3 | Quarterly |

**Rate limits:** 120 requests/นาที (free tier)
**API Key:** ต้องสมัครที่ fred.stlouisfed.org (ฟรี)

### 4.3 Supabase

```python
# ข้อกำหนดการใช้งาน
from supabase import create_client

supabase = create_client(
    url=os.getenv("SUPABASE_URL"),
    key=os.getenv("SUPABASE_SERVICE_KEY")  # service key สำหรับ server-side
)

# Write example
supabase.table("daily_prices").upsert(records).execute()

# Read example
result = supabase.table("regime_history") \
    .select("*") \
    .order("date", desc=True) \
    .limit(1) \
    .execute()
```

**Connection:** ใช้ service key (ไม่ใช่ anon key) สำหรับ pipeline
**Upsert strategy:** ใช้ `ON CONFLICT DO UPDATE` สำหรับ price/macro data เพื่อรองรับ FRED revision

### 4.4 Gmail

```python
# src/alerts/gmail.py
import smtplib
from email.mime.text import MIMEText
import os

def send_alert(subject: str, body: str) -> bool:
    """Send alert via Gmail SMTP. Returns True on success, False if credentials missing."""
    sender   = os.getenv("GMAIL_SENDER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not sender or not password:
        return False   # non-fatal — log warning, don't crash pipeline
    recipient = os.getenv("GMAIL_RECIPIENT") or sender
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[FlowMacro] {subject}"
    msg["From"]    = sender
    msg["To"]      = recipient
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.sendmail(sender, recipient, msg.as_string())
    return True
```

**Email subject/body สำหรับ regime change:**
```
Subject: [FlowMacro] Regime: REFLATION (65%)

Date:            2026-05-30
Regime:          REFLATION
Previous:        GOLDILOCKS
Confidence:      65.2%
Growth Score:    72.1
Inflation Score: 68.4
Reason:          regime changed: GOLDILOCKS → REFLATION
```

**Email subject/body สำหรับ data failure:**
```
Subject: [FlowMacro] yfinance Fetch Failed (partial)

Failed tickers: DBC, SLV
Continuing with remaining 18 tickers.
```

**Credentials:** Gmail App Password (ไม่ใช้ password หลัก) — ต้องเปิด 2FA ก่อน สมัครได้ที่ myaccount.google.com → Security → App passwords

---

## 5. Secrets Management (การจัดการ Secrets)

### 5.1 Local Development

ไฟล์ `.env` (gitignored):
```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJxxxx
FRED_API_KEY=xxxxxxxxxxxxxxxxxxxx
GMAIL_SENDER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
GMAIL_RECIPIENT=your@gmail.com
```

โหลดใน code:
```python
from dotenv import load_dotenv
load_dotenv()
```

### 5.2 GitHub Actions (Production)

ตั้งค่าใน Repository → Settings → Secrets and variables → Actions:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `FRED_API_KEY`
- `GMAIL_SENDER`
- `GMAIL_APP_PASSWORD`
- `GMAIL_RECIPIENT`

ใช้ใน workflow:
```yaml
env:
  SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
  SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
  FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
  GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
  GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
  GMAIL_RECIPIENT: ${{ secrets.GMAIL_RECIPIENT }}
```

**ไม่มี secrets ที่ต่างกันระหว่าง local และ production** — code เดียวกัน อ่าน env variables เหมือนกัน

---

## 6. GitHub Actions Workflows (Workflow Definitions)

### 6.1 Daily Job

```yaml
# .github/workflows/daily_job.yml
name: Daily Price Fetch & Indicators

on:
  schedule:
    - cron: '30 1 * * *'  # 01:30 UTC = 08:30 Bangkok
  workflow_dispatch:       # manual trigger สำหรับ test

jobs:
  daily-run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python scripts/run_daily.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_RECIPIENT: ${{ secrets.GMAIL_RECIPIENT }}
```

### 6.2 Weekly Job

```yaml
# .github/workflows/weekly_job.yml
name: Weekly Regime Detection

on:
  schedule:
    - cron: '0 2 * * 5'  # 02:00 UTC Friday = 09:00 Bangkok
  workflow_dispatch:

jobs:
  weekly-run:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: python scripts/run_weekly.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_RECIPIENT: ${{ secrets.GMAIL_RECIPIENT }}
```

### 6.3 Heartbeat (ป้องกัน auto-pause)

```yaml
# .github/workflows/heartbeat.yml
name: Heartbeat (prevent auto-pause)

on:
  schedule:
    - cron: '0 0 1 */2 *'  # ทุก 2 เดือน วันที่ 1

jobs:
  heartbeat:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          git config user.email "bot@flowmacro"
          git config user.name "FlowMacro Bot"
          echo "$(date)" > .heartbeat
          git add .heartbeat
          git commit -m "chore: heartbeat $(date +%Y-%m-%d)"
          git push
```

---

## 7. Testing Requirements (ข้อกำหนดการทดสอบ)

### 7.1 Unit Tests (ที่ต้องมีก่อน Phase 1 Done)

| Test File | ฟังก์ชันที่ test | Assertion หลัก |
|-----------|-----------------|----------------|
| `test_percentile.py` | `calculate_percentile_rank()` | output อยู่ 0-100, inverse indicators ถูก invert |
| `test_scorer.py` | `compute_growth_score()`, `compute_inflation_score()` | weighted average ถูกต้อง, output 0-100 |
| `test_regime_classifier.py` | `classify_regime()` | confidence formula ถูกต้อง, TRANSITIONING เมื่อ confidence < 40% |

```python
# ตัวอย่าง test case ที่ต้องมี
def test_transitioning_when_low_confidence():
    result = classify_regime(growth_score=48, inflation_score=52)
    # growth_conf = 2 * abs(48-50) = 4
    # inflation_conf = 2 * abs(52-50) = 4
    # confidence = min(4, 4) = 4 < 40 → TRANSITIONING
    assert result.regime == "TRANSITIONING"
    assert result.confidence == 4.0

def test_stagflation_classification():
    result = classify_regime(growth_score=20, inflation_score=85)
    # growth_conf = 60, inflation_conf = 70, confidence = 60 ≥ 40 → classify
    # growth < 50, inflation > 50 → STAGFLATION
    assert result.regime == "STAGFLATION"
    assert result.confidence == 60.0
```

### 7.2 Integration Tests (อยู่นอก scope Phase 1 แต่ plan ไว้)

- Test FRED API connection จริง (ใช้ mock สำหรับ CI)
- Test Supabase write/read roundtrip
- Test Gmail alert delivery

---

## 8. Dependencies (Library ที่ใช้)

```txt
# requirements.txt
python-dotenv==1.0.1
yfinance==0.2.55
fredapi==0.5.2
supabase==2.15.0
vectorbt==0.26.3
pandas==2.2.3
numpy==1.26.4
structlog==24.4.0
requests==2.32.3
streamlit==1.45.1
plotly==5.24.1
pytest==8.3.4
```

**Version pinning:** pin ทุก library เพื่อ reproducibility ระหว่าง local และ GitHub Actions

**Last validated:** 2026-05-30
⚠️ **NEEDS VALIDATION:** ตรวจสอบ compatibility ระหว่าง vectorbt 0.26.x กับ pandas 2.2.x ก่อน install

---

## 9. Cost Estimate (ประมาณการค่าใช้จ่าย)

| Service | Plan | ค่าใช้จ่าย/เดือน | หมายเหตุ |
|---------|------|-----------------|---------|
| Supabase | Free | $0 | 500MB storage, เพียงพอสำหรับ Phase 1 |
| GitHub Actions | Free | $0 | ~155 min/เดือน << 2,000 min limit |
| FRED API | Free | $0 | ต้องสมัคร API key |
| Gmail | Free | $0 | SMTP with App Password, 500 emails/day limit |
| yfinance | Free | $0 | unofficial API |
| **รวม Phase 1** | | **$0/เดือน** | |

**Phase 2+ estimate (เพิ่ม Claude API):** ~$10-30/เดือน ขึ้นกับ frequency

---

## Revision History (ประวัติการแก้ไข)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-30 | Pae | Initial draft — tech requirements + 5 ADRs + DB schema + API specs |
