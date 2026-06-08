# Product Requirements Document (เอกสารข้อกำหนดผลิตภัณฑ์)

**Project Name (ชื่อโครงการ):** Global Macro Trading Bot
**Code Name (รหัสโครงการ):** FlowMacro
**Version:** 1.3
**Author:** Pae (Patchara Phookheaw)
**Date:** 2026-05-30
**Status:** Design Locked — Ready for Phase 1 Implementation

---

## 1. Executive Summary (สรุปย่อสำหรับผู้บริหาร)

FlowMacro เป็น **personal trading bot** สำหรับ position trading (ถือ 1-3 เดือน) บนสินทรัพย์ระดับโลก (Global Multi-Asset) โดยใช้กลยุทธ์ **Macro Regime Detection + Fund Flow Confirmation + AI-Assisted Thesis Generation**

ระบบจะตรวจจับ market regime ปัจจุบัน (Goldilocks / Reflation / Stagflation / Deflation) แล้วเลือก asset class ที่เหมาะสมกับ regime นั้น พร้อมยืนยันด้วย fund flow signals ก่อนส่ง alert ให้ผู้ใช้ตัดสินใจเทรด โดยใช้ **Alpaca** (paper trading, Phase 1-3) และ **IBKR** (live trading, Phase 4+) เป็น broker หลัก และ **Binance API** สำหรับ crypto

**Core value proposition (คุณค่าหลัก):** ลด emotional trading และ replicate แนวคิดของ global macro hedge fund (เช่น Bridgewater, Brevan Howard) ในระดับ solo trader ด้วยต้นทุนต่ำกว่า $100/เดือน

---

## 2. Problem Statement (คำอธิบายปัญหา)

### 2.1 Problem (ปัญหาที่ต้องแก้)

Retail trader 90% ขาดทุนเพราะ:
1. **Emotional trading** — เทรดตามข่าว/อารมณ์ ไม่มี systematic framework
2. **No regime awareness** — ใช้ strategy เดียวกันในทุก market condition (ทั้งที่ bull/bear ต้องการ strategy ต่างกัน)
3. **Information overload** — ข้อมูล macro/flow/news เยอะเกินกว่าจะประมวลผลด้วยมือ
4. **Inconsistent execution** — รู้ว่าควรทำอะไร แต่ไม่ทำตามแผน

### 2.2 Why now? (ทำไมต้องทำตอนนี้?)

- **AI maturity**: Claude/Gemini สามารถอ่าน news + generate trading thesis ได้ในระดับที่ใช้งานได้จริงแล้ว
- **Data accessibility**: FRED, yfinance, CoinGecko, ETF.com มี free/cheap API ที่ครอบคลุม global market
- **Broker APIs**: Alpaca (free paper trading), IBKR (low commission) เปิดให้ retail เข้าถึง institutional-grade execution
- **Personal context**: ผู้ใช้มี background liquidity management 15+ ปี และทักษะ AI engineering — เป็นช่วงที่เหมาะที่สุดในการ build

### 2.3 Cost of inaction (ผลกระทบหากไม่ทำ)

- ขาด systematic framework → ยังคงเทรดด้วยอารมณ์ → loss compounds over time
- Knowledge gap ระหว่างที่รู้กับที่ทำได้ → ไม่ได้ใช้ประโยชน์จาก finance + AI background
- เสีย opportunity cost ในการ build IP สำหรับ freelance/independent career path

---

## 3. Goals & Success Metrics (เป้าหมายและตัวชี้วัด)

### 3.1 Business Goals (เป้าหมายธุรกิจ)

| Goal | Metric | Target | Timeframe |
|------|--------|--------|-----------|
| G1: Generate consistent risk-adjusted returns | Sharpe Ratio (live) | > 1.0 | 12 เดือนหลัง launch |
| G2: Outperform benchmark on drawdown | Max Drawdown vs 60/40 benchmark | < 15% และน้อยกว่า benchmark | Rolling 12 เดือน |
| G3: Outperform benchmark on return | Annual return vs 60/40 benchmark | > benchmark + 3% | Rolling 12 เดือน |
| G4: Validate strategy in paper trading | Paper trading P&L vs backtest | Within ±20% | 6 เดือน paper phase |
| G5: Build maintainable foundation | Clean modular codebase | แต่ละ module import ได้อิสระ, มี test coverage บน core logic | Phase 1 end |

**Benchmark definition (สำคัญมาก):**
- **Primary benchmark**: 60/40 portfolio — SPY (60%) + TLT (40%) rebalanced รายไตรมาส
- **Secondary benchmark**: Buy-and-hold SPY (100%)
- เหตุผล: FlowMacro claim ว่า better risk-adjusted return — ต้องวัดเทียบกับ 60/40 ไม่ใช่แค่ SPY เพราะ 60/40 คือ baseline ที่ทำได้โดยไม่ต้องใช้ strategy ซับซ้อน
- ถ้า FlowMacro ทำได้ต่ำกว่า 60/40 ทั้ง return และ Sharpe → ต้อง pause และ review strategy ทั้งหมด

### 3.2 User Goals (เป้าหมายผู้ใช้)

- **G-U1**: ใช้เวลาดู/ตัดสินใจไม่เกิน 30 นาที/วัน
- **G-U2**: รับ alert พร้อม thesis ที่อ่านเข้าใจได้ใน 2 นาที
- **G-U3**: มั่นใจในการตัดสินใจ (ไม่ต้อง doubt ทุก trade)

### 3.3 Non-Goals (ไม่ใช่เป้าหมายในเวอร์ชันนี้)

- ❌ **Day trading / scalping** — focus position trading เท่านั้น
- ❌ **Fully autonomous execution** ในเฟสแรก — ต้องมี human-in-the-loop
- ❌ **Multi-user / SaaS product** — เป็น personal tool ก่อน (พิจารณา productize ภายหลัง)
- ❌ **Options / derivatives strategies** — เฉพาะ ETF + spot crypto เท่านั้น
- ❌ **High-frequency signals** — refresh signals แค่ daily, regime แค่ weekly

---

## 4. Target Users (ผู้ใช้กลุ่มเป้าหมาย)

### 4.1 Primary User (ผู้ใช้หลัก)

**Persona: Pae — Solo Trader / Finance Professional**

- **Background**: Finance professional 15+ ปี (liquidity management), MBA Finance, กำลังเปลี่ยนสายเป็น AI Engineer
- **Capital**: **100,000 THB (~$3,000 USD)** — เป้าหมาย Build + Validate ก่อน, top-up ถึง $10,000+ ก่อน Phase 4 live
- **Time commitment**: 30 นาที/วัน + 1-2 ชม./สัปดาห์ สำหรับ review
- **Risk tolerance**: Moderate — ยอมรับ drawdown 15-20% เพื่อแลกกับ return ที่สูงกว่า index
- **Technical skill**: Python proficient, comfortable กับ AI tools, vibecoding style

### 4.2 Secondary Users (ผู้ใช้รอง)

ไม่มีในเวอร์ชันนี้ (single-user system) — แต่ design ต้อง modular พอที่จะ extend เป็น multi-user ได้ในอนาคต

---

## 5. Scope (ขอบเขต)

### 5.1 In Scope — Phase 1 (อยู่ในขอบเขต — เฟส 1: เดือน 1-2)

- ✅ Data ingestion pipeline (prices + FRED macro indicators เท่านั้น — ไม่รวม fund flows)
- ✅ Regime detection module (4 regimes + TRANSITIONING state, 3-tier indicator framework, percentile rank normalization)
- ✅ Backtest engine — **ขั้นต่ำ 20 ปี (2005-2025)** ครอบคลุม GFC 2008, dot-com recovery, COVID crash, rate hike cycle 2022 ⚠️ DBC/SLV เปิดตัว Feb/Apr 2006 — backtest commodity regime ก่อน 2006 ต้องใช้ GLD+USO แทน
- ✅ Backtest methodology: walk-forward analysis (train 10 ปี, test 5 ปี, rolling) + out-of-sample period ≥ 3 ปี
- ✅ Transaction cost model ใน backtest (bid-ask spread 0.05%, ETF premium/discount ±0.1%, commission $1/trade)
- ✅ Benchmark tracking: 60/40 portfolio (SPY 60% + TLT 40%) rebalanced รายไตรมาส
- ✅ Streamlit dashboard สำหรับ monitor regime + signals + staleness flags + THB equivalent
- ✅ Logging + error tracking infrastructure
- ✅ GitHub Actions cron scheduler (daily 08:00 + Friday 08:30 Bangkok time) + Gmail alert เมื่อ job fail
- ❌ **Crypto (BTC/ETH) — ออกจาก Phase 1** เพิ่มใน Phase 2 (Binance API ข้อมูลย้อนหลังไม่ครบ 20 ปี)

### 5.2 In Scope — Phase 2 (เฟส 2: เดือน 3-4)

- ✅ Fund flow signals (ETF flows, COT positioning)
- ✅ Cross-asset correlation analysis
- ✅ AI thesis generation (Claude API integration)
- ✅ Position sizing engine (Kelly + risk parity)
- ✅ Alert system (Gmail)

### 5.3 In Scope — Phase 3 (เฟส 3: เดือน 5-6)

- ✅ Paper trading integration (custom simulation, Supabase-backed — ไม่ผ่าน Alpaca API)
- ✅ Performance tracking dashboard (P&L, Sharpe, drawdown)
- ✅ Trade journal (auto-log ทุก trade พร้อม thesis ที่ใช้ตัดสินใจ)

### 5.4 Out of Scope (อยู่นอกขอบเขต)

- ❌ Live trading กับเงินจริง (ทำหลังเฟส 3 ผ่าน criteria)
- ❌ Options / futures / leveraged products
- ❌ Day trading / intraday signals
- ❌ Social/community features
- ❌ Mobile app (web dashboard เท่านั้น)
- ❌ FX hedging — ไม่ hedge THB/USD exposure (แสดง THB equivalent ใน dashboard เพื่อ reference เท่านั้น ไม่ใช่ accounting จริง)

---

## 6. Asset Universe (จักรวาลสินทรัพย์)

ระบบจะ trade เฉพาะ instruments ที่ liquid + accessible ผ่าน IBKR:

| Asset Class | Instruments | Rationale |
|-------------|-------------|-----------|
| US Equity | SPY, QQQ, IWM | Core risk-on exposure |
| International Equity | EFA, EEM, FXI, EWJ | Regional rotation |
| Bonds | TLT, IEF, HYG | Risk-off + carry |
| Commodities | GLD, USO, DBC, SLV | Inflation hedge |
| FX (via ETF) | UUP, FXE, FXY | Macro view |
| Crypto | BTC, ETH (Binance API) | High-beta liquidity gauge |

**Total: ~18 instruments** — เพียงพอสำหรับ position trading โดยไม่ overwhelm

⚠️ **ASSUMPTION:** ใช้ ETF เป็น proxy สำหรับ asset class ทั้งหมด (ไม่ trade futures/individual stocks)

---

## 7. Key Features (ฟีเจอร์หลัก)

### F1: Regime Detection Engine

ตรวจจับ market regime รายสัปดาห์ (Goldilocks / Reflation / Stagflation / Deflation) โดยแยก indicators ออกเป็น 3 ชั้นตาม lead time:

**Tier 1 — Leading Indicators (นำตลาด 3-6 เดือน) — น้ำหนัก 50%**
| Indicator | Source | ความสำคัญ |
|-----------|--------|-----------|
| Yield curve slope (2y-10y Treasury spread) | FRED | Leading recession indicator ที่แม่นที่สุด |
| Credit spread (IG vs HY) | FRED (BAMLH0A0HYM2) | นำ equity drawdown 2-3 เดือน |
| 5-year breakeven inflation rate | FRED (T5YIE) | Market expectation ของ inflation |
| Conference Board Leading Economic Index | FRED | Composite leading index |

**Tier 2 — Coincident Indicators (สะท้อนปัจจุบัน) — น้ำหนัก 30%**
| Indicator | Source | ความสำคัญ |
|-----------|--------|-----------|
| ISM Manufacturing PMI | FRED | Business cycle gauge |
| Copper/Gold ratio | yfinance (HG=F / GC=F) | Risk appetite proxy |
| SPY vs 200-day MA distance | yfinance | Equity trend strength |
| DXY trend (UUP 20-day MA) | yfinance | Dollar strength |

**Tier 3 — Lagging Confirmation (ยืนยัน regime หลังเกิด) — น้ำหนัก 20%**
| Indicator | Source | ความสำคัญ |
|-----------|--------|-----------|
| CPI YoY | FRED | Realized inflation |
| Unemployment rate | FRED | Labor market health |
| Real GDP growth (quarterly) | FRED | Actual economic output |

**Classification Algorithm (ตัดสินใจแล้ว):**

Regime มาจาก 2 แกน: **Growth** (สูง/ต่ำ) × **Inflation** (สูง/ต่ำ)

```
                 Inflation สูง    Inflation ต่ำ
Growth สูง   →   REFLATION        GOLDILOCKS
Growth ต่ำ   →   STAGFLATION      DEFLATION
```

**Step 1 — Normalization:** แปลงแต่ละ indicator เป็น percentile rank เทียบกับ **5 ปีที่ผ่านมา** (rolling window) — robust ต่อ outliers กว่า Z-score

**Step 2 — Axis Scoring:**

Tier weights (50/30/20) apply within each axis — indicator ที่อยู่ใน Tier 1 มีน้ำหนักสูงกว่า Tier 2/3 แม้อยู่ใน axis เดียวกัน

| Axis | Indicator | Tier | Direction |
|------|-----------|------|-----------|
| **Growth** | Yield curve slope | T1 (50%) | สูง = growth ดี |
| **Growth** | Credit spread (IG vs HY) | T1 (50%) | **inverse**: spread สูง = growth ต่ำ |
| **Growth** | LEI | T1 (50%) | สูง = growth ดี |
| **Growth** | ISM PMI | T2 (30%) | สูง = growth ดี |
| **Growth** | Copper/Gold ratio | T2 (30%) | สูง = risk-on / growth ดี |
| **Growth** | SPY vs 200MA | T2 (30%) | สูง = growth ดี |
| **Growth** | Unemployment rate | T3 (20%) | **inverse**: สูง = growth ต่ำ |
| **Growth** | Real GDP growth | T3 (20%) | สูง = growth ดี |
| **Inflation** | 5Y breakeven inflation | T1 (50%) | สูง = inflation คาดสูง |
| **Inflation** | DXY trend (UUP) | T2 (30%) | **inverse**: USD แข็ง = imported inflation ต่ำ |
| **Inflation** | CPI YoY | T3 (20%) | สูง = inflation จริงสูง |

- `growth_score` = weighted average ของ percentile ranks ของ growth indicators (tier weight ของแต่ละตัว)
- `inflation_score` = weighted average ของ percentile ranks ของ inflation indicators (tier weight ของแต่ละตัว)
- ทั้งสองค่าอยู่ใน range 0–100

**Step 3 — Confidence Formula:**
```python
# แต่ละแกนคำนวณ confidence แยกกัน (0-100%)
growth_conf = 2 * abs(growth_score - 50)       # growth_score=80 → 60%, growth_score=25 → 50%
inflation_conf = 2 * abs(inflation_score - 50)  # inflation_score=90 → 80%

# regime_confidence = ค่าต่ำสุดของสองแกน (ต้องทั้งคู่ชัดเจน)
confidence = min(growth_conf, inflation_conf)   # 0-100%
```

ตัวอย่าง: growth=35 (low), inflation=85 (high) → min(30%, 70%) = **30% confidence → TRANSITIONING**
ตัวอย่าง: growth=20 (very low), inflation=85 (high) → min(60%, 70%) = **60% confidence → STAGFLATION** ✅

**Step 4 — Regime Classification:**
- ถ้า `confidence < 40%` → `TRANSITIONING` (อย่างน้อยหนึ่งแกนยังไม่ชัดเจน)
- ถ้า `confidence ≥ 40%` → map quadrant ตาม growth_score > 50 และ inflation_score > 50
- TRANSITIONING exit: confidence ≥ 50% (hysteresis band ป้องกัน flip-flop)

**Data Staleness:** ใช้ "last known value" (carry forward) สำหรับ indicators ที่ยังไม่ update — แสดง staleness flag ใน dashboard ว่า stale กี่วัน

**Regime transition detection:**
- `TRANSITIONING` เกิดขึ้นอัตโนมัติเมื่อ confidence < 60%
- ใน `TRANSITIONING` state: ลด position size ลง 50% และ block การเปิด position ใหม่จนกว่า confidence ≥ 70%
- Transition period คาดอยู่ที่ 4-8 สัปดาห์ — ระบบต้อง log ทุก week ว่า signal ชี้ไปทิศไหน

**Output ต่อ run:**
- `current_regime`: GOLDILOCKS / REFLATION / STAGFLATION / DEFLATION / TRANSITIONING
- `regime_confidence`: 0-100% (จาก distance formula)
- `growth_score`: 0-100 (percentile composite)
- `inflation_score`: 0-100 (percentile composite)
- `leading_score`: composite ของ Tier 1 เท่านั้น (early warning)
- `staleness_flags`: dict ของแต่ละ indicator ว่า stale กี่วัน

**Regime-to-Asset Allocation (Phase 1 — Equal Weight):**

| Regime | Overweight (equal weight ใน 80% ของพอร์ต) | Avoid |
|--------|------------------------------------------|-------|
| **GOLDILOCKS** | SPY, QQQ, IWM, EFA, EEM | TLT, GLD, USO |
| **REFLATION** | GLD, SLV, DBC, USO, EEM, IWM | TLT, IEF, UUP |
| **STAGFLATION** | GLD, SLV, DBC, UUP | SPY, QQQ, EEM, HYG |
| **DEFLATION** | TLT, IEF, UUP | SPY, GLD, USO, HYG |
| **TRANSITIONING** | ลด position ทุกตัว 50%, Cash buffer เพิ่มเป็น 50% | ไม่เปิด position ใหม่ |

Cash buffer ขั้นต่ำ **20%** ทุก regime (ยกเว้น TRANSITIONING = 50%)

### F2: Fund Flow Signal Generator
- Track ETF flows (US sectors, country ETFs, bond ETFs)
- COT positioning (CFTC weekly report)
- Percentile rank normalization vs 4-week และ 12-week baseline (consistent กับ Phase 1 regime engine)
- Smart money vs retail flow classification

### F3: AI Thesis Generator
- รวบรวม signals + news headlines + economic calendar
- ใช้ Claude API generate thesis ในรูปแบบ:
  - Recommended action (BUY / HOLD / SELL / AVOID)
  - Conviction score (1-10)
  - Position size suggestion (% of portfolio)
  - Key risks
  - Time horizon

### F4: Position Sizing & Risk Engine
- Kelly Criterion (fractional, 25-50%)
- Correlation check (block correlated trades > 0.7)
- Portfolio heat limit (max 8% unrealized loss)
- Cash buffer enforcement (min 20%)

### F5: Alert System
- Daily morning alert (Bangkok ~8:15 AM หลัง daily job เสร็จ): regime + top opportunities
- Real-time alert: เมื่อ regime change หรือ high-conviction signal เกิดขึ้น
- ส่งผ่าน Gmail (SMTP App Password)

### F6: Paper Trading Integration
- Custom simulation (ไม่ผ่าน Alpaca) — `broker/paper_portfolio.py` + Supabase series `paper_total_value`
- คำนวณ week-over-week return จาก actual prices × regime weights ทุกศุกร์
- Dashboard หน้า Paper Trading P&L Tracker — equity curve + weekly log + regime overlay
- เทียบ paper performance vs backtest projection

### F7: Monitoring Dashboard
- Streamlit web app (local)
- Current regime + confidence score + growth/inflation scores
- Staleness flags: แสดงแต่ละ indicator ว่า stale กี่วัน
- Open positions + P&L แสดงทั้ง **USD และ THB equivalent** (ใช้ yfinance ticker `THB=X`)
- Signal log + thesis archive
- Performance metrics (Sharpe, Sortino, Max DD, Win Rate)
- Backtest summary chart (FlowMacro vs 60/40 benchmark)

---

## 8. User Experience Principles (หลักการประสบการณ์ผู้ใช้)

1. **Glanceable** — เปิด dashboard 30 วินาทีต้องเข้าใจสถานการณ์ portfolio
2. **Decision-ready** — alert ต้องบอกชัด: ทำอะไร, เท่าไหร่, เพราะอะไร, เสี่ยงอะไร
3. **Transparent** — ทุก signal ต้อง explainable ไม่ใช่ black box
4. **Reversible** — มี kill switch + manual override ทุก stage
5. **Honest about uncertainty** — แสดง confidence score เสมอ ไม่ overconfident

---

## 9. Engineering Principles (หลักการทางวิศวกรรม)

### 9.1 Debuggability (Debug ง่าย)

ทุก module ต้องมี:

- **Structured logging**: ใช้ `structlog` หรือ `loguru` กับ JSON format
- **Run ID tracing**: ทุก daily run มี unique `run_id` (UUID) สำหรับ trace ตลอด pipeline
- **Checkpoint state**: บันทึก intermediate state (signals, regime score) ใน Supabase สำหรับ replay
- **Error specificity**: Error message ต้องระบุ (1) module, (2) input ที่ทำให้ fail, (3) suggested fix
- **Health endpoint**: `/health` endpoint แสดง status ของ data sources ทุกตัว
- **Reproducibility**: Backtest ต้อง deterministic (fixed random seed, frozen data snapshot)

**ตัวอย่าง requirement:**
> ทุก signal calculation ต้อง log: (1) input data summary (min/max/mean/last_value), (2) calculation timestamp, (3) output value, (4) confidence score, (5) run_id สำหรับ trace

### 9.2 Current Best Practices Validation (ถูกต้องและเหมาะสมที่สุดในปัจจุบัน)

**Tech stack decisions (last validated: 2026-05-15):**

| Component | Choice | Rationale | Alternatives Considered |
|-----------|--------|-----------|------------------------|
| Language | Python 3.12+ | Standard สำหรับ finance/ML, ecosystem แข็งแกร่ง | Rust (rejected: ecosystem ยังเล็ก) |
| Data store | Supabase (Postgres) | Free tier เพียงพอ, มี realtime + auth built-in | DuckDB (rejected: ไม่มี hosted), TimescaleDB (over-engineered) |
| Backtest | `vectorbt` | ✅ ยืนยันแล้ว: vectorized, รัน walk-forward 20 ปีได้เร็ว, รองรับ Python 3.12+, active maintenance (backtrader rejected: หยุด develop 2023) |
| LLM | Claude Sonnet 4 หรือ 4.5 | Best reasoning สำหรับ macro analysis | GPT-4 (rejected: cost สูงกว่า), Gemini (acceptable as backup) |
| Dashboard | Streamlit | Quick prototype, ผู้ใช้คุ้นเคย | Next.js (over-engineered สำหรับ personal tool) |
| Scheduling | GitHub Actions cron | Free, version-controlled | Airflow (over-engineered), AWS Lambda (vendor lock-in) |
| Broker (paper) | Custom PaperBroker (Supabase-backed) | ✅ deployed 2026-06-06: ไม่มี API dependency, $0 opex, ใช้ actual prices จาก Supabase — Alpaca skip เพราะ Phase 4 ใช้ IBKR โดยตรง | Alpaca (rejected: dead-end — live phase ใช้ IBKR ไม่ใช่ Alpaca) |
| Broker (live) | IBKR (Singapore) | ✅ ยืนยันแล้ว: รองรับ Thailand, 150+ markets, 34 ประเทศ, forex + intl stocks ที่ Alpaca ไม่มี | Alpaca live (US-listed assets only — ไม่เพียงพอสำหรับ global macro) |
| Crypto | Binance API | ✅ ยืนยันแล้ว: Alpaca crypto ไม่รองรับ non-US users — ต้องใช้ Binance แยก | Coinbase Advanced (acceptable as backup) |

**Broker Strategy (revised 2026-06-08):**
```
Phase 1–3 (paper trading): Custom PaperBroker (self-built simulation)
→ เหตุผล: Alpaca ถูก skip — Phase 4 ใช้ IBKR โดยตรง, Alpaca เป็น dead-end (US assets only)
→ implementation: broker/paper_portfolio.py + Supabase series paper_total_value
→ ทุนเริ่มต้น: $3,000 virtual, รันจริงตั้งแต่ 2026-06-06

Phase 4+ (live trading): IBKR Singapore
→ เหตุผล: global market access, forex, intl stocks, commission ต่ำ
→ ต้องการ: เงินทุนขั้นต่ำ $10,000, KYC ใช้เวลา 1-2 สัปดาห์
→ Crypto: Binance API แยกต่างหาก
```

✅ **Secrets management:** `.env` + `python-dotenv` สำหรับ local development, GitHub Actions Secrets สำหรับ production — ใช้ code เดียวกัน

✅ **Tech stack ทุกตัวยืนยันแล้ว — ไม่มี NEEDS VALIDATION คงเหลือ**

---

## 10. Constraints & Assumptions (ข้อจำกัดและสมมติฐาน)

### 10.1 Constraints (ข้อจำกัด)

- **Budget**: < $100/เดือน operating cost (data + API + hosting)
- **Solo developer**: ออกแบบต้องเรียบง่ายพอที่คนเดียวจะ maintain ได้
- **No insider data**: ใช้เฉพาะ public data sources
- **Regulatory**: ไม่ใช่ investment advice (สำหรับใช้ส่วนตัวเท่านั้น)

### 10.2 Assumptions (สมมติฐาน)

- ✅ **A1 (UPDATED 2026-06-08)**: Paper trading ใช้ custom simulation แทน Alpaca — Alpaca skip เพราะ Phase 4 ใช้ IBKR โดยตรง (Alpaca live = US assets only, ไม่เพียงพอสำหรับ global macro). IBKR Singapore รองรับ Thai traders, KYC 1-2 สัปดาห์
- ✅ **A2 (VERIFIED)**: ทุนตั้งต้น **100,000 THB (~$3,000 USD)** — เป้าหมายหลักคือ Build + Validate ก่อน ไม่ใช่ live trade ทันที Phase 4 (IBKR live) ต้องการ top-up ทุนให้ถึง $10,000+ ก่อน
- ✅ **A3**: Data quality จาก yfinance/FRED เพียงพอสำหรับ position trading (ไม่ต้องการ tick data)
- ✅ **A4**: Macro regime framework (4 regimes) ครอบคลุม market condition ส่วนใหญ่
- ✅ **A5**: Position trading 1-3 เดือนทำให้ overfitting risk ต่ำกว่า day trading
- ✅ **A6 (VERIFIED)**: Crypto ต้องใช้ Binance API แยก — Alpaca crypto ไม่รองรับ non-US users (confirmed Oct 2025)

---

## 11. Risks & Mitigation (ความเสี่ยงและการบรรเทา)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| R1: Backtest overfitting | High | High | Out-of-sample testing, walk-forward analysis, Sharpe cap (ถ้า > 2.0 = สงสัย overfit) |
| R2: Regime change ทำให้ strategy ใช้ไม่ได้ | Medium | High | Walk-forward retraining ทุก 6 เดือน, monitor regime classifier accuracy |
| R3: Data source ล่ม (yfinance rate limit, FRED API change) | Medium | Medium | Multi-source fallback, cache data ใน Supabase |
| R4: LLM hallucination ใน thesis | Medium | Medium | Structured output + validation rules, ไม่ให้ LLM ตัดสินใจ execute เอง |
| R5: Slippage ใน live trading vs backtest | High | Medium | ใช้ bid/ask + commission ใน backtest, paper trade 6 เดือนก่อน live |
| R6: Emotional override (ผู้ใช้ไม่ทำตาม signal) | High | High | Trade journal บังคับ log เหตุผลถ้า override |
| R7: Single point of failure (solo developer) | High | Medium | Docs ครบ, code modular, ใช้ managed services เป็นหลัก |
| R8: Macro regime classifier เลือก regime ผิด | Medium | High | Confidence threshold (ไม่ trade ถ้า confidence < 60%), human review ก่อน execute |

---

## 11.5 Drawdown Recovery Plan (แผนรับมือเมื่อพอร์ตขาดทุน)

> แผนนี้ต้องเขียนและ commit ไว้ล่วงหน้าตอนใจเย็น ห้ามแก้ไขในช่วงที่ตลาดผันผวนหนัก

ระบบจะ trigger แผนนี้อัตโนมัติตาม drawdown level โดยวัดจาก **peak-to-current NAV**:

### Level 1 — Yellow Alert (Drawdown 8-12%)
- **Action**: ไม่เปิด position ใหม่จนกว่า drawdown จะกลับมาต่ำกว่า 8%
- **Action**: Review regime classification ว่า classify ถูกต้องหรือไม่
- **Action**: ลด position size ของ open positions ลง 25%
- **Notification**: Gmail alert พร้อม drawdown % และ open positions ทั้งหมด
- **Review**: Manual review ทุกวัน (แทน weekly)

### Level 2 — Orange Alert (Drawdown 12-18%)
- **Action**: Close ทุก position ที่ขาดทุนเกิน -15% ทันที
- **Action**: ลด position size ทั้งพอร์ตลง 50%
- **Action**: เพิ่ม cash buffer เป็น 40% (จาก 20%)
- **Action**: หยุด AI thesis generation ชั่วคราว — ใช้ manual judgment แทน
- **Notification**: Alert ฉุกเฉิน พร้อม P&L breakdown รายตัว
- **Review**: ทบทวน strategy กับ backtest ว่า drawdown นี้ใน range ที่ backtest คาดไว้หรือไม่

### Level 3 — Red Alert (Drawdown > 18%)
- **Action**: **หยุดการเทรดทั้งหมด** — ปิดทุก position ที่มี
- **Action**: ระบบเข้าสู่ "Capital Preservation Mode" — ถือ cash 100%
- **Action**: ทบทวน strategy ทั้งหมดใหม่ก่อน restart (ใช้เวลาอย่างน้อย 4 สัปดาห์)
- **Restart condition**: ต้องทำ fresh backtest + paper trading 1 เดือนก่อนกลับมา live

### Recovery conditions (เงื่อนไขกลับมา trade ปกติ)
```
จาก Level 1 → Normal:
  - drawdown < 5% และ regime confidence ≥ 70%

จาก Level 2 → Level 1:
  - drawdown < 10% และ strategy review ผ่าน

จาก Level 3 → ต้องผ่านทั้งหมด:
  - Fresh backtest ผ่าน (Sharpe > 1.0 บน out-of-sample)
  - Paper trading 1 เดือน (ไม่ขาดทุน)
  - Root cause analysis เสร็จสมบูรณ์ (เขียนเป็น document)
```

### สิ่งที่ห้ามทำในทุก alert level
- ❌ ห้ามเพิ่ม position เพื่อ average down โดยไม่มี signal ใหม่
- ❌ ห้ามแก้ไข stop loss หรือ risk parameter ระหว่างที่ drawdown กำลังดำเนินอยู่
- ❌ ห้าม override ระบบโดยไม่ log เหตุผลใน trade journal

---



## 12. Success Criteria สำหรับการ Go-Live (เกณฑ์การปล่อยใช้งานจริง)

ก่อนจะเปลี่ยนจาก paper trading เป็น live trading ต้องผ่านเกณฑ์ **ทั้งหมด** นี้:

**Strategy validation:**
- [ ] Backtest ครอบคลุม ≥ 20 ปี (2005-2025) รวม GFC 2008 และ COVID 2020
- [ ] Backtest Sharpe Ratio ≥ 1.0 บน **out-of-sample period** (ไม่ใช่ in-sample)
- [ ] Backtest outperform 60/40 benchmark ทั้ง return และ Sharpe บน out-of-sample
- [ ] Walk-forward analysis ผ่าน (ไม่มี period ที่ strategy ขาดทุนเกิน -25%)
- [ ] Leading indicator layer (Tier 1) พิสูจน์ได้ว่า predict regime change ได้ล่วงหน้า ≥ 4 สัปดาห์ ในข้อมูลย้อนหลัง

**Paper trading validation:**
- [ ] Paper trading รันต่อเนื่อง ≥ 6 เดือน
- [ ] Paper Sharpe Ratio ≥ 1.0 (อย่างน้อย 2 ไตรมาสติดต่อกัน)
- [ ] Paper Max Drawdown ≤ 15%
- [ ] Paper performance อยู่ใน ±20% ของ backtest projection
- [ ] Paper outperform 60/40 benchmark ใน 6 เดือน paper period

**System readiness:**
- [ ] Drawdown Recovery Plan ทดสอบแล้ว (simulate Level 1-3 trigger ครบทุก level)
- [ ] ไม่มี critical bug ใน production logs 3 เดือนล่าสุด
- [ ] Risk controls ทดสอบแล้ว (stop loss, position size limit, correlation block ทำงานจริง)
- [ ] Transaction cost model verified (paper P&L หลังหัก estimated cost ยังผ่านเกณฑ์)

**Personal readiness:**
- [ ] ผู้ใช้ comfortable กับ system และ trust ใน signals
- [ ] ผู้ใช้อ่านและ commit กับ Drawdown Recovery Plan แล้ว
- [ ] Capital allocation ตัดสินใจแล้ว (เริ่มด้วย ≤ 30% ของเงินที่ตั้งใจใช้)

---

## 13. Open Questions (คำถามที่ยังต้องตอบ)

✅ **Open questions ทุกข้อ resolved แล้ว — พร้อม implement Phase 1**

1. ✅ ~~Capital ตั้งต้นที่จะใช้คือเท่าไหร่?~~ — **RESOLVED: 100,000 THB (~$3,000 USD), เป้าหมาย Build + Validate ก่อน**
2. ✅ ~~ต้องการเริ่มเขียน code จาก module ไหนก่อน?~~ — **RESOLVED: Regime Detection + Data Ingestion พร้อมกันในชั้นเดียว**
3. ✅ ~~ระบบควรพิจารณา THB exposure (FX hedge) หรือไม่?~~ — **RESOLVED: Track USD + THB equivalent ใน dashboard ผ่าน yfinance `THB=X` ไม่ hedge จริง**
4. ✅ ~~ต้องการ integrate กับ QFI Terminal หรือเป็น standalone tool?~~ — **RESOLVED: Standalone ก่อน ไม่ออกแบบ integration ล่วงหน้า**
5. ✅ ~~Backtest library?~~ — **RESOLVED: `vectorbt`**
6. ✅ ~~Alpaca ใช้ได้จาก Thailand หรือไม่?~~ — **MOOT: Alpaca ถูก skip ทั้งหมด (2026-06-08) — paper = custom simulation, live = IBKR Singapore**
7. ✅ ~~IBKR Singapore สำหรับ Thai trader?~~ — **RESOLVED: รองรับ confirmed**
8. ✅ ~~Crypto broker?~~ — **RESOLVED: ใช้ Binance API แยก (Phase 2+)**

---

## 13.5 Phase 1 "Done" Definition (เกณฑ์ความสำเร็จ Phase 1)

Phase 1 ถือว่าเสร็จสมบูรณ์เมื่อผ่านเกณฑ์ **ทั้งหมด** นี้:

- [ ] Regime detection รันได้ครบ 1 สัปดาห์จริง → output `current_regime`, `confidence`, `growth_score`, `inflation_score`, `staleness_flags` ครบถ้วน
- [ ] Data ครบทุก indicator ใน 3 tiers (FRED + yfinance) — ไม่มี silent gap
- [ ] Backtest 20 ปี (2005–2025) รันบน vectorbt ได้ → แสดง Sharpe, Max Drawdown, Annual Return เทียบ 60/40 benchmark
- [ ] Streamlit dashboard แสดง: regime ปัจจุบัน + confidence + staleness flags + backtest summary + THB equivalent
- [ ] Gmail alert ทำงานเมื่อ data source fail — ไม่มี silent failure
- [ ] GitHub Actions cron รันตรงเวลา (daily 08:00 + Friday 08:30 Bangkok) + heartbeat commit ป้องกัน auto-pause

---

## 13.6 Run Schedule (ตารางการรัน)

```
ทุกวัน (GitHub Actions 08:00 Bangkok time):
  → ดึง price data จาก yfinance (ETF universe ทั้งหมด + THB=X)
  → คำนวณ daily indicators (SPY vs 200MA, Copper/Gold ratio, UUP trend)
  → อัปเดต staleness flags
  → บันทึกลง Supabase
  → ถ้าข้อมูลขาดหาย → Gmail alert ทันที

ทุกวันศุกร์ (GitHub Actions 08:30 Bangkok time):
  → ดึง FRED data (yield curve, credit spread, CPI, unemployment, LEI ฯลฯ)
  → คำนวณ percentile rank (rolling 5 ปี) สำหรับทุก indicator
  → คำนวณ growth_score + inflation_score
  → ตัดสิน regime + confidence (distance formula)
  → ถ้า regime เปลี่ยน หรือ confidence < 60% → Gmail alert พร้อม summary
  → อัปเดต Streamlit dashboard
```

---

## 14. Related Documents (เอกสารที่เกี่ยวข้อง)

จะถูกสร้างใน iteration ถัดไป:

- `global-macro-bot-user-stories.md` — User Stories + Acceptance Criteria
- `global-macro-bot-technical-req.md` — Technical Requirements + ADR
- `global-macro-bot-pipeline-flow.md` — Data Pipeline + Decision Flow

---

## 15. Revision History (ประวัติการแก้ไข)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-15 | Pae | Initial draft |
| 1.1 | 2026-05-15 | Pae | Broker strategy confirmed: Alpaca (paper) → IBKR Singapore (live), Binance API (crypto). Updated assumptions A1/A6, resolved 3 open questions |
| 1.2 | 2026-05-22 | Pae | Senior Quant review applied: (1) F1 Regime Detection เพิ่ม 3-tier indicator framework + leading indicators (yield curve, credit spread) + TRANSITIONING state, (2) Backtest scope ขยายเป็น 20 ปี + transaction cost model + walk-forward methodology, (3) เพิ่ม benchmark definition (60/40 portfolio), (4) เพิ่ม Section 11.5 Drawdown Recovery Plan (Level 1-3), (5) อัปเดต Go-Live Criteria ให้ครอบคลุมทั้งหมด |
| 1.3 | 2026-05-30 | Pae | Design Locked — Grilling session resolved all open questions: (1) ทุนตั้งต้น 100,000 THB, เป้าหมาย Build+Validate ก่อน live, (2) Backtest library = vectorbt, (3) Regime algorithm: 2-axis percentile rank (rolling 5y) + distance confidence formula, (4) Asset allocation: equal weight Phase 1, (5) Crypto ออกจาก Phase 1, (6) THB equivalent tracking ใน dashboard, (7) Standalone (ไม่ integrate QFI Terminal), (8) Run schedule: daily 08:00 + Friday 08:30 BKK, (9) Secrets: .env + python-dotenv, (10) เพิ่ม Section 13.5 Phase 1 Done Criteria + Section 13.6 Run Schedule + Regime-to-Asset Allocation table |

---

| 1.4 | 2026-05-30 | Pae | Scrutiny fixes: (1) แก้ confidence formula เป็น min(growth_conf, inflation_conf) พร้อมลด threshold เป็น 40%, (2) แก้ credit spread ย้ายไป growth axis, (3) reconcile Tier weights กับ Axis weights เพิ่มตาราง indicator-to-axis mapping, (4) อัปเดต Section 4.1 capital figure, (5) แก้ Section 5.4 FX hedging conflict, (6) อัปเดต G5 ตัด QFI Terminal, (7) แก้ F5 alert time, (8) F2 เปลี่ยนเป็น percentile rank, (9) เพิ่ม note DBC/SLV data availability 2006 |

---

| 1.5 | 2026-06-08 | Pae | Broker strategy revised: (1) Alpaca paper trading ถูก skip ทั้งหมด — ใช้ custom PaperBroker + Supabase-backed simulation แทน (deployed 2026-06-06), (2) Phase 4 ใช้ IBKR Singapore โดยตรง ไม่มี Alpaca intermediary, (3) อัปเดต Section 5.3/F6/tech stack/A1/open question 6 ให้สะท้อนความจริง, (4) เพิ่ม NEXTPLAN.md สำหรับ Phase 4 IBKR integration |

---

**Last validated:** 2026-06-08
**Next review:** หลัง Phase 3 paper trading pass (ก่อนเริ่ม Phase 4)
