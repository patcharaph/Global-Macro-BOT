# FlowMacro — Global Macro Trading Bot

Personal position trading bot ที่ตรวจจับ macro regime และ allocate ETF โดยอัตโนมัติ

**Strategy:** Regime Detection (Growth × Inflation) → Equal-weight ETF allocation → Weekly rebalance

**เป้าหมาย:** Beat 60/40 benchmark (SPY 60% + TLT 40%) บน risk-adjusted return ใน 6 เดือน paper trading

---

## How It Works

```
ทุกวันศุกร์ 08:30 (Bangkok)
├── ดึง FRED indicators (yield curve, credit spread, CPI, ฯลฯ)
├── ดึง price data (18 ETFs + futures)
├── คำนวณ percentile rank (rolling 5 ปี)
├── คำนวณ Growth Score + Inflation Score (0-100)
├── จำแนก Regime → GOLDILOCKS / REFLATION / STAGFLATION / DEFLATION / TRANSITIONING
└── ส่ง email alert + อัปเดต dashboard
```

### 4 Regimes

|  | Inflation ต่ำ | Inflation สูง |
|--|---------------|---------------|
| **Growth สูง** | 🟢 GOLDILOCKS | 🟡 REFLATION |
| **Growth ต่ำ** | 🔵 DEFLATION  | 🔴 STAGFLATION |

**TRANSITIONING** — เมื่อ confidence < 40% → ลด position ลง 50%, ไม่เปิด position ใหม่

### Confidence Formula
```python
confidence = min(2 * abs(growth_score - 50), 2 * abs(inflation_score - 50))
# TRANSITIONING เมื่อ confidence < 40%, exit เมื่อ >= 50%
```

---

## Project Structure

```
flowmacro/
├── config.py              # Settings จาก .env
├── data/
│   ├── sources/
│   │   ├── fred.py        # FRED API fetcher
│   │   └── prices.py      # yfinance fetcher + staleness
│   └── store.py           # Supabase read/write
├── regime/
│   ├── indicators.py      # Indicator registry + percentile rank
│   ├── scorer.py          # Growth/Inflation axis scores
│   └── classifier.py      # Regime + confidence + hysteresis
├── portfolio/
│   └── allocator.py       # Regime → equal-weight allocation
├── backtest/
│   └── engine.py          # vectorbt wrapper + 60/40 benchmark
├── alerts/
│   └── gmail.py           # Gmail SMTP alert
├── dashboard/
│   └── app.py             # Streamlit dashboard
└── scheduler/
    ├── daily.py           # Daily price refresh (08:00 Bangkok)
    └── weekly.py          # Friday regime detection (08:30 Bangkok)
```

---

## Setup

### Prerequisites
- Python 3.12+
- [FRED API Key](https://fred.stlouisfed.org/docs/api/api_key.html) (ฟรี)
- [Supabase](https://supabase.com) project (free tier)
- Gmail App Password (Google Account → Security → 2-Step Verification → App Passwords)

### 1. Clone + Install

```bash
git clone https://github.com/patcharaph/Global-Macro-BOT.git
cd Global-Macro-BOT
pip install -r requirements.txt
```

### 2. Environment Variables

```bash
cp .env.example .env
# แก้ไข .env ใส่ค่าจริง
```

```env
FRED_API_KEY=your_fred_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=sb_secret_your_service_role_key
GMAIL_SENDER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GMAIL_RECIPIENT=your@gmail.com
```

### 3. Supabase Schema

รัน SQL ใน **Supabase → SQL Editor:**

```sql
-- Time series data (prices + FRED indicators)
create table if not exists raw_series (
  id        bigserial primary key,
  series_id text      not null,
  date      date      not null,
  value     float8,
  unique (series_id, date)
);
create index if not exists idx_raw_series_lookup on raw_series (series_id, date);
alter table raw_series disable row level security;

-- Weekly regime history
create table if not exists regime_history (
  id              bigserial primary key,
  run_date        date      not null unique,
  regime          text      not null,
  confidence      float     not null,
  growth_score    float     not null,
  inflation_score float     not null,
  created_at      timestamptz default now()
);
alter table regime_history disable row level security;
```

### 4. GitHub Secrets (สำหรับ GitHub Actions)

ไปที่ **Settings → Secrets and variables → Actions** แล้วเพิ่ม:

| Secret | Description |
|--------|-------------|
| `FRED_API_KEY` | FRED API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key (`sb_secret_...`) |
| `GMAIL_SENDER` | Gmail address สำหรับส่ง alert |
| `GMAIL_APP_PASSWORD` | Gmail App Password (16 chars) |
| `GMAIL_RECIPIENT` | Email ที่รับ alert |

---

## Usage

### Run Dashboard (Local)

```bash
streamlit run flowmacro/dashboard/app.py
# เปิด http://localhost:8501
```

### Run Scheduler Manually

```bash
# Weekly job (regime detection + email alert)
python -m flowmacro.scheduler.weekly

# Daily job (price data refresh only)
python -m flowmacro.scheduler.daily
```

### GitHub Actions Schedule

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `daily.yml` | ทุกวัน 08:00 Bangkok | Refresh prices + derived indicators |
| `weekly.yml` | ทุกศุกร์ 08:30 Bangkok | Regime detection + email alert + heartbeat commit |

Trigger manual run: **Actions → workflow → Run workflow**

---

## Indicators

### Growth Axis (50% Tier 1 / 30% Tier 2 / 20% Tier 3)

| Indicator | Source | Tier | Direction |
|-----------|--------|------|-----------|
| Yield curve (2y-10y) | FRED T10Y2Y | 1 | Normal |
| Credit spread (HY) | FRED BAMLH0A0HYM2 | 1 | Inverse |
| Leading Economic Index | FRED USSLIND | 1 | Normal |
| ISM Manufacturing PMI | FRED NAPM | 2 | Normal |
| Copper/Gold ratio | yfinance HG=F/GC=F | 2 | Normal |
| SPY vs 200MA | yfinance SPY | 2 | Normal |
| Unemployment rate | FRED UNRATE | 3 | Inverse |
| Real GDP growth | FRED A191RL1Q225SBEA | 3 | Normal |

### Inflation Axis

| Indicator | Source | Tier | Direction |
|-----------|--------|------|-----------|
| 5Y Breakeven inflation | FRED T5YIE | 1 | Normal |
| DXY trend (UUP 20MA) | yfinance UUP | 2 | Inverse |
| CPI YoY | FRED CPIAUCSL | 3 | Normal |

---

## Asset Allocation (Phase 1 — Equal Weight, 20% Cash Buffer)

| Regime | Assets |
|--------|--------|
| GOLDILOCKS | SPY, QQQ, IWM, EFA, EEM |
| REFLATION | GLD, SLV, DBC, USO, EEM, IWM |
| STAGFLATION | GLD, SLV, DBC, UUP |
| DEFLATION | TLT, IEF, UUP |
| TRANSITIONING | Cash only |

---

## Phase 1 Go-Live Criteria

- [ ] Regime detection รันต่อเนื่อง ≥ 4 สัปดาห์ ไม่มี silent failure
- [ ] Backtest 20 ปี Sharpe ≥ 1.0 บน out-of-sample
- [ ] Backtest outperform 60/40 ทั้ง return และ Sharpe
- [ ] Dashboard แสดง regime + staleness + THB equivalent ได้ถูกต้อง
- [ ] Gmail alert ทำงานเมื่อ job fail

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12 |
| Data — Macro | FRED API (`fredapi`) |
| Data — Prices | yfinance |
| Storage | Supabase (Postgres) |
| Backtest | vectorbt |
| Dashboard | Streamlit |
| Alerts | Gmail SMTP |
| Scheduler | GitHub Actions cron |
| Broker (paper) | Alpaca *(Phase 3)* |
| Broker (live) | IBKR Singapore *(Phase 4+)* |

---

## Disclaimer

Personal tool สำหรับใช้ส่วนตัวเท่านั้น ไม่ใช่ investment advice
