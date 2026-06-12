# FlowMacro — Global Macro Trading Bot

Personal position trading bot ที่ตรวจจับ macro regime และ allocate ETF โดยอัตโนมัติ

**Strategy V3:** Softmax Regime Probabilities → Blended Allocation → Momentum Filter → Vol Targeting → Weekly Rebalance

**เป้าหมาย:** Beat 60/40 benchmark (SPY 60% + AGG 40%) บน risk-adjusted return ผ่าน paper trading → live IBKR Singapore

---

## How It Works

```
ทุกวันศุกร์ 08:30 (Bangkok)
├── ดึง FRED indicators (yield curve, credit spread, CPI, ฯลฯ)
├── ดึง CFTC COT data (S&P 500, 10Y Treasury, Gold, Crude)
├── ดึง price data (21 tickers + BTC spot)
├── คำนวณ percentile rank (rolling 5 ปี)
├── คำนวณ Growth Score + Inflation Score (0–100)
├── V3: Softmax regime probabilities (4 regimes)
├── V3: Blended allocation = Σ p_k × w_k (ทุก regime พร้อมกัน)
├── V3: Momentum filter (cut assets ที่ return < 0 ใน 13W + 26W)
├── V3: Vol targeting (scale to 10% annual portfolio vol)
├── ML shadow: XGBoost prediction (logging only — ไม่กระทบ Portfolio A)
├── Portfolio A: อัปเดต paper portfolio $3,000 (rule-based V3)
├── Portfolio B: คำนวณ virtual portfolio $3,000 (V3 + ML blend 30%)
├── สร้าง AI Macro Thesis (OpenRouter → Claude Sonnet)
└── ส่ง email alert + อัปเดต dashboard
```

### 4 Regimes

|  | Inflation ต่ำ | Inflation สูง |
|--|---------------|---------------|
| **Growth สูง** | GOLDILOCKS | REFLATION |
| **Growth ต่ำ** | DEFLATION  | STAGFLATION |

**TRANSITIONING** — เกิดขึ้น naturally เมื่อ softmax entropy สูง (ไม่มี regime โดดเด่น) → portfolio drift ไปถือ defensive basket อัตโนมัติ

### V3 Regime Probabilities

```python
# Softmax จาก Euclidean distance ถึง centroids ของแต่ละ regime
prob_k = exp(-d_k / tau) / Σ exp(-d_j / tau)

# Blended allocation — smooth drift แทน hard switch
w_asset = Σ_k (p_k × w_k_asset)
```

---

## Backtest Results (V3 Walk-Forward)

Walk-forward: 5Y train / 2Y test / 1Y roll — 11 windows (2010–2026)

| Strategy | OOS Sharpe (mean) | OOS MaxDD (mean) |
|----------|--------------------|------------------|
| V2B (equal-weight, legacy) | 0.61 | ~14% |
| **V3 (softmax blend)** | **1.06** | **8.8%** |

Acceptance criteria: **8/8 PASS**

---

## ML A/B Test (Phase 3 Validation)

XGBoost shadow mode — trained on 17 features, NBER-labeled 2000–2024

| Portfolio | Strategy | Capital | Status |
|-----------|----------|---------|--------|
| A | Rule-based V3 (softmax) | $3,000 live tracking | Active since 2026-06-03 |
| B | V3 + XGBoost blend (30% ML / 70% rule) | $3,000 virtual | Active since 2026-06-13 |

ผล 26 สัปดาห์จะประกอบการตัดสิน ML graduation criteria ธ.ค. 2026

---

## Project Structure

```
flowmacro/
├── config.py              # Settings จาก .env
├── data/
│   ├── sources/
│   │   ├── fred.py        # FRED API fetcher
│   │   ├── prices.py      # yfinance fetcher + staleness
│   │   ├── cot.py         # CFTC Legacy COT fetcher
│   │   └── binance.py     # BTC spot price (Binance public API)
│   └── store.py           # Supabase read/write + retry
├── regime/
│   ├── indicators.py      # Indicator registry + percentile rank
│   ├── scorer.py          # Growth/Inflation axis scores
│   ├── classifier.py      # V2B regime + confidence + hysteresis
│   ├── probabilities.py   # V3 softmax probabilities + ML blend
│   └── ml_predictor.py    # XGBoost shadow-mode classifier
├── portfolio/
│   ├── allocator.py       # V3 blended allocation (REGIME_WEIGHTS)
│   ├── momentum_filter.py # Cut assets with negative 13W + 26W momentum
│   ├── vol_targeting.py   # Scale portfolio to 10% annual vol
│   └── rebalance.py       # Rebalance band check + trade list
├── backtest/
│   └── engine.py          # vectorbt wrapper + walk-forward
├── thesis/
│   └── generator.py       # AI macro thesis via OpenRouter
├── broker/
│   ├── base.py            # Abstract BrokerBase
│   └── paper_portfolio.py # Portfolio A (Supabase-backed) + Portfolio B (virtual)
├── alerts/
│   └── gmail.py           # Gmail SMTP alert
├── dashboard/
│   ├── app.py             # Main page: regime + action banner + thesis + weights
│   └── pages/
│       ├── 2_backtest.py       # V3 walk-forward results + V2B legacy expander
│       ├── 3_health.py         # System health + staleness
│       ├── 4_data.py           # Raw data explorer
│       ├── 5_paper_trading.py  # Portfolio A P&L + returns vs benchmark + position P&L
│       └── 6_ab_test.py        # ML A/B Test — Portfolio A vs B equity curves + metrics
└── scheduler/
    ├── daily.py           # Daily price refresh (08:00 Bangkok)
    └── weekly.py          # Friday regime detection + portfolio update (08:30 Bangkok)

scripts/
└── migrate_paper_portfolio_ml.sql   # Supabase schema for Portfolio B table
```

---

## Setup

### Prerequisites
- Python 3.10+
- [FRED API Key](https://fred.stlouisfed.org/docs/api/api_key.html) (ฟรี)
- [Supabase](https://supabase.com) project (free tier)
- Gmail App Password (Google Account → Security → 2-Step Verification → App Passwords)
- [OpenRouter API Key](https://openrouter.ai/keys) (AI thesis)

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
OPENROUTER_API_KEY=sk-or-your_openrouter_key
```

### 3. Supabase Schema

รัน SQL ใน **Supabase → SQL Editor:**

```sql
-- Time series data (prices + FRED indicators + pipeline outputs)
create table if not exists raw_series (
  id        bigserial primary key,
  series_id text      not null,
  date      date      not null,
  value     float8,
  unique (series_id, date)
);
create index if not exists idx_raw_series_lookup on raw_series (series_id, date);
alter table raw_series disable row level security;

-- Weekly regime history (rule-based)
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

-- ML shadow mode regime history
create table if not exists regime_history_ml (
  id              bigserial primary key,
  run_date        date      not null unique,
  ml_regime       text      not null,
  ml_confidence   float     not null,
  rb_regime       text      not null,
  agrees          boolean   not null,
  created_at      timestamptz default now()
);
alter table regime_history_ml disable row level security;

-- AI macro thesis
create table if not exists thesis_runs (
  id              bigserial primary key,
  run_date        date      not null,
  regime          text      not null,
  confidence      float     not null,
  growth_score    float     not null,
  inflation_score float     not null,
  recommendation  text      not null,
  conviction      int       not null,
  reasoning       text      not null,
  risks           text      not null,
  model           text      not null,
  created_at      timestamptz default now()
);
alter table thesis_runs disable row level security;
```

สำหรับ Portfolio B (ML A/B test) รัน `scripts/migrate_paper_portfolio_ml.sql` แยกต่างหาก

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
| `OPENROUTER_API_KEY` | OpenRouter key สำหรับ AI thesis |

---

## Usage

### Run Dashboard (Local)

```bash
streamlit run flowmacro/dashboard/app.py
# เปิด http://localhost:8501
```

Dashboard มี 6 pages:
- **Home** — Regime + action banner + signal strength + AI thesis + COT signals + blended weights
- **Backtest** — V3 walk-forward results + V2B legacy expander + equity curves
- **Health** — Data staleness + pipeline run history
- **Data** — Raw data explorer (browse + download any series จาก Supabase)
- **Paper Trading** — Portfolio A P&L, equity curve, weekly log, returns vs SPY/60-40, position P&L
- **A/B Test** — Portfolio A (rule-based) vs B (ML-blend 30%) equity curves + Sharpe + MaxDD

### Run Scheduler Manually

```bash
# Weekly job (regime + COT + ML shadow + paper trading + AI thesis + email alert)
python -m flowmacro.scheduler.weekly

# Daily job (price data refresh only)
python -m flowmacro.scheduler.daily
```

### GitHub Actions Schedule

| Workflow | Schedule | Description |
|----------|----------|-------------|
| `daily.yml` | ทุกวัน 08:00 Bangkok | Refresh prices + derived indicators |
| `weekly.yml` | ทุกศุกร์ 08:30 Bangkok | Regime detection + portfolio update + email alert |

Trigger manual run: **Actions → workflow → Run workflow**

---

## Indicators

### Growth Axis (50% Tier 1 / 30% Tier 2 / 20% Tier 3)

| Indicator | Source | Tier | Direction |
|-----------|--------|------|-----------|
| Yield curve (10y-2y) | FRED T10Y2Y | 1 | Normal |
| Credit spread (Baa-10y) | FRED BAA10Y | 1 | Inverse |
| Initial Claims | FRED ICSA | 1 | Inverse |
| Industrial Production: Mfg | FRED IPMAN | 2 | Normal |
| Copper/Gold ratio | yfinance HG=F/GC=F | 2 | Normal |
| SPY vs 200MA | yfinance SPY | 2 | Normal |
| COT S&P 500 net speculative | CFTC | 2 | Normal |
| COT 10Y Treasury net speculative | CFTC | 2 | Inverse |
| Unemployment rate | FRED UNRATE | 3 | Inverse |
| Real GDP growth | FRED A191RL1Q225SBEA | 3 | Normal |

### Inflation Axis

| Indicator | Source | Tier | Direction |
|-----------|--------|------|-----------|
| 5Y Breakeven inflation | FRED T5YIE | 1 | Normal |
| DXY trend (UUP 20MA) | yfinance UUP | 2 | Inverse |
| COT Gold net speculative | CFTC | 2 | Normal |
| CPI YoY | FRED CPIAUCSL (derived) | 3 | Normal |
| COT Crude Oil net speculative | CFTC | 3 | Normal |

COT source: [CFTC Legacy Futures-Only](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) — ออกทุกวันศุกร์ (ข้อมูล ณ วันอังคาร)

---

## Asset Allocation (V3 — Softmax Blended, 20% Cash Buffer)

| Regime | Assets | Weights |
|--------|--------|---------|
| GOLDILOCKS | SPY, QQQ, IWM, EFA, EEM, BTC-USD | 20/16/12/12/13/7% |
| REFLATION | SPY, IWM, EEM, GLD, DBC | 12/8/20/10/30% |
| STAGFLATION | GLD, SLV, DBC, UUP | 34/8/24/14% |
| DEFLATION | TLT, IEF, UUP, SHY | 30/25/15/10% |
| TRANSITIONING (fallback) | SHY, GLD | 25/25% |

Portfolio weights = Σ p_k × w_k_asset (ทุก regime พร้อมกัน ถ่วงน้ำหนักด้วย softmax probs)

---

## Paper Trading (Phase 3 Validation)

เริ่ม 2026-06-03 — Portfolio A + B รันอัตโนมัติทุก Friday:

**Portfolio A (Rule-based V3):**
1. อ่าน V3 blended weights
2. คำนวณ week return จาก actual prices × weights
3. บันทึก `paper_total_value` series → Supabase

**Portfolio B (ML-blend 30%, virtual):**
1. Blend regime probs: 30% XGBoost + 70% rule-based
2. คำนวณ blended weights จาก ML-adjusted probs
3. บันทึก `paper_portfolio_ml` table → Supabase

**Go-Live criteria** (หลัง 4–8 สัปดาห์ paper trading + ทุน $10k USD):
- [ ] Regime detection รันต่อเนื่อง ≥ 4 สัปดาห์ ไม่มี silent failure
- [ ] Backtest OOS Sharpe ≥ 1.0 (V3: ผ่านแล้ว 1.06)
- [ ] Paper portfolio outperform 60/40 benchmark
- [ ] Dashboard แสดง regime + staleness ถูกต้อง

**ML Graduation criteria** (ธ.ค. 2026 — หลัง 26 สัปดาห์ A/B test):
- [ ] Portfolio B Sharpe > Portfolio A Sharpe
- [ ] ≥ 15/26 สัปดาห์ที่ B outperform A
- [ ] MaxDD B ≤ MaxDD A + 2%

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.10+ |
| Data — Macro | FRED API (`fredapi`) |
| Data — Prices | yfinance |
| Data — COT | CFTC public ZIP files |
| Data — BTC | Binance public API |
| Storage | Supabase (Postgres + Storage) |
| Backtest | vectorbt (walk-forward) |
| ML | XGBoost (shadow mode, quarterly retrain) |
| Dashboard | Streamlit (space neon theme) |
| Alerts | Gmail SMTP |
| Scheduler | GitHub Actions cron |
| AI Thesis | OpenRouter (Claude Sonnet) |
| Broker (paper) | Custom PaperBroker + Supabase-backed |
| Broker (live) | IBKR Singapore *(Phase 4+)* |

---

## Tests

```bash
pytest  # 143 tests, 0 failures
```

---

## Disclaimer

Personal tool สำหรับใช้ส่วนตัวเท่านั้น ไม่ใช่ investment advice
