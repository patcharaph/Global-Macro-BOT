# User Stories & Acceptance Criteria (เรื่องราวผู้ใช้และเกณฑ์การยอมรับ)

**Project (โครงการ):** FlowMacro — Phase 1
**References PRD (อ้างอิง):** global-macro-bot-prd.md v1.4
**Version:** 1.0
**Author:** Pae (Patchara Phookheaw)
**Date:** 2026-05-30
**Status:** Draft

---

## Epic Overview (ภาพรวม Epic)

Phase 1 มี 5 epics หลัก ครอบคลุม 6 เดือน build และ validate ก่อน live trading:

| Epic | ชื่อ | PRD Feature | Priority |
|------|------|-------------|----------|
| E1 | Data Ingestion | F1 (data layer) | Must Have |
| E2 | Regime Detection | F1 (engine) | Must Have |
| E3 | Backtest Engine | Phase 1 scope | Must Have |
| E4 | Monitoring Dashboard | F7 | Must Have |
| E5 | Scheduler & Alerting | F5 (partial) | Must Have |

---

## E1: Data Ingestion (การดึงข้อมูล)

### US-1.1 — ดึงราคา ETF รายวัน

**As a** solo trader
**I want** ระบบดึงราคาปิดของ ETF ทุกตัวใน asset universe รายวัน
**So that** ฉันมีข้อมูลราคาที่ครบถ้วนสำหรับคำนวณ indicators และ backtest

**Acceptance Criteria (เกณฑ์การยอมรับ):**
- [ ] ดึงราคาได้ครบทุก ticker: SPY, QQQ, IWM, EFA, EEM, FXI, EWJ, TLT, IEF, HYG, GLD, USO, DBC, SLV, UUP, FXE, FXY และ THB=X (18 tickers)
- [ ] ดึง OHLCV + Adjusted Close ทุกวัน (ไม่ใช่แค่ Close)
- [ ] ถ้า market ปิด (US holiday) → ไม่ error แต่ log ว่า "market closed"
- [ ] บันทึกลง Supabase table `daily_prices` พร้อม `run_id`, `ticker`, `date`, `close`, `adj_close`, `volume`
- [ ] ถ้าดึง ticker ใดไม่ได้ → log error + ส่ง Gmail alert ทันที ไม่รอ retry
- [ ] ดึงข้อมูลย้อนหลัง 20 ปี (2005-01-01 ถึง present) สำหรับ backtest ได้ใน single run

**Edge Cases (กรณีพิเศษ):**
- yfinance rate limit → retry 3 ครั้ง interval 5 วินาที → ถ้ายัง fail → alert + ใช้ last known value
- ticker เปลี่ยนชื่อ (เช่น corporate action) → log warning พร้อม ticker ที่ไม่พบ

---

### US-1.2 — ดึง FRED macro indicators รายสัปดาห์

**As a** solo trader
**I want** ระบบดึง macro indicators ทุกตัวจาก FRED รายสัปดาห์ (ทุกวันศุกร์)
**So that** ฉันมีข้อมูล macro ล่าสุดสำหรับคำนวณ regime

**Acceptance Criteria:**
- [ ] ดึง indicators ครบทุกตัวตาม 3-tier framework:
  - Tier 1 (leading): `T10Y2Y` (yield curve), `BAMLH0A0HYM2` (credit spread), `T5YIE` (breakeven inflation), `USSLIND` (LEI)
  - Tier 2 (coincident): `MANEMP` (ISM PMI proxy via FRED), `UNRATE` (unemployment)
  - Tier 3 (lagging): `CPIAUCSL` (CPI), `A191RL1Q225SBEA` (Real GDP)
  - Market-based (yfinance): Copper/Gold ratio (`HG=F`/`GC=F`), SPY vs 200MA, UUP 20MA
- [ ] บันทึกลง Supabase table `macro_indicators` พร้อม `indicator_id`, `date`, `value`, `source`, `fetched_at`, `run_id`
- [ ] FRED indicators บางตัว update รายเดือนหรือรายไตรมาส → ใช้ last known value (carry forward) และ set `staleness_days` อย่างถูกต้อง
- [ ] ถ้า FRED API key หมดอายุหรือ rate limit → Gmail alert พร้อม indicator ที่ fail

**Edge Cases:**
- FRED data revision → overwrite ค่าเก่าในตาราง พร้อม log ว่า "revised from X to Y"
- GDP quarterly → carry forward ค่าล่าสุดจนกว่าจะมีค่าใหม่ และแสดง staleness_days จริงใน dashboard

---

### US-1.3 — ตรวจสอบ staleness ของข้อมูล

**As a** solo trader
**I want** เห็น staleness flag ของแต่ละ indicator ใน dashboard
**So that** ฉันรู้ว่า indicator ตัวไหนใช้ข้อมูลเก่าและควรให้น้ำหนักน้อยลง

**Acceptance Criteria:**
- [ ] ทุก indicator มี `staleness_days` = จำนวนวันที่ผ่านมาตั้งแต่ update ล่าสุด
- [ ] Dashboard แสดง staleness flag: 🟢 (0-7 วัน), 🟡 (8-30 วัน), 🔴 (>30 วัน)
- [ ] ถ้า indicator ที่เป็น Tier 1 stale > 14 วัน → Gmail alert อัตโนมัติ
- [ ] Staleness ไม่ทำให้ระบบ crash → ใช้ last known value และแสดง flag เสมอ

---

## E2: Regime Detection (การตรวจจับ Market Regime)

### US-2.1 — คำนวณ percentile rank ของแต่ละ indicator

**As a** solo trader
**I want** ระบบแปลง indicator แต่ละตัวเป็น percentile rank (0-100) เทียบกับ 5 ปีที่ผ่านมา
**So that** ค่า indicators ที่มี scale ต่างกันสามารถเปรียบเทียบและรวมได้อย่างถูกต้อง

**Acceptance Criteria:**
- [ ] ใช้ rolling window 5 ปี (260 weeks) สำหรับทุก indicator
- [ ] percentile rank = 0 หมายถึงต่ำสุดใน 5 ปี, 100 หมายถึงสูงสุดใน 5 ปี
- [ ] Inverse indicators (credit spread, unemployment, DXY) ถูก invert ก่อนคำนวณ percentile
- [ ] บันทึก `percentile_rank` รายตัวลง Supabase พร้อม `run_id` สำหรับ trace
- [ ] ถ้าข้อมูลน้อยกว่า 5 ปี (ช่วงแรก backtest) → ใช้ expanding window แทน และ log warning

---

### US-2.2 — คำนวณ growth_score และ inflation_score

**As a** solo trader
**I want** ระบบรวม percentile rank ของ indicators แต่ละแกนเป็น growth_score และ inflation_score
**So that** ฉันเห็นภาพรวมของ growth และ inflation ในตัวเลขเดียว

**Acceptance Criteria:**
- [ ] `growth_score` = weighted average ของ indicators ใน growth axis ตาม tier weight:
  - Tier 1 indicators: yield curve, credit spread, LEI (น้ำหนัก 50% รวมกันใน Tier 1)
  - Tier 2: ISM PMI, Copper/Gold, SPY vs 200MA (น้ำหนัก 30% รวมกัน)
  - Tier 3: unemployment (inverse), Real GDP (น้ำหนัก 20% รวมกัน)
- [ ] `inflation_score` = weighted average ของ indicators ใน inflation axis:
  - Tier 1: 5Y breakeven (50%)
  - Tier 2: DXY (inverse) (30%)
  - Tier 3: CPI YoY (20%)
- [ ] ทั้งสองค่าอยู่ในช่วง 0-100
- [ ] บันทึก `growth_score`, `inflation_score`, `leading_score` (Tier 1 only composite) ลง Supabase

---

### US-2.3 — ตัดสิน regime และ confidence

**As a** solo trader
**I want** ระบบตัดสินว่าตลาดอยู่ใน regime ใดพร้อม confidence score
**So that** ฉันรู้ว่าควร overweight asset class ใดและมั่นใจแค่ไหน

**Acceptance Criteria:**
- [ ] คำนวณ confidence ด้วยสูตร:
  ```
  growth_conf = 2 * abs(growth_score - 50)
  inflation_conf = 2 * abs(inflation_score - 50)
  confidence = min(growth_conf, inflation_conf)
  ```
- [ ] ถ้า confidence < 40% → `current_regime = TRANSITIONING`
- [ ] ถ้า confidence ≥ 40% → map quadrant:
  - growth > 50 และ inflation > 50 → REFLATION
  - growth > 50 และ inflation ≤ 50 → GOLDILOCKS
  - growth ≤ 50 และ inflation > 50 → STAGFLATION
  - growth ≤ 50 และ inflation ≤ 50 → DEFLATION
- [ ] TRANSITIONING exit threshold = 50% (hysteresis band)
- [ ] บันทึก output ครบใน Supabase `regime_history`: `run_id`, `date`, `current_regime`, `regime_confidence`, `growth_score`, `inflation_score`, `leading_score`, `staleness_flags`

---

### US-2.4 — แสดง regime-to-asset allocation suggestion

**As a** solo trader
**I want** เห็น asset class ที่ควร overweight/avoid ตาม regime ปัจจุบัน
**So that** ฉันมีข้อมูลเบื้องต้นสำหรับตัดสินใจ (Phase 1 ยังไม่ execute อัตโนมัติ)

**Acceptance Criteria:**
- [ ] แสดง allocation table ตาม regime (equal weight, 80% ของพอร์ต):
  - GOLDILOCKS: Overweight SPY, QQQ, IWM, EFA, EEM / Avoid TLT, GLD, USO
  - REFLATION: Overweight GLD, SLV, DBC, USO, EEM, IWM / Avoid TLT, IEF, UUP
  - STAGFLATION: Overweight GLD, SLV, DBC, UUP / Avoid SPY, QQQ, EEM, HYG
  - DEFLATION: Overweight TLT, IEF, UUP / Avoid SPY, GLD, USO, HYG
  - TRANSITIONING: ลด position ทุกตัว 50%, cash 50%, ไม่เปิดใหม่
- [ ] แสดงเป็น read-only ใน dashboard — Phase 1 ไม่มี auto-execute
- [ ] Cash buffer ขั้นต่ำ 20% แสดงใน dashboard เสมอ (TRANSITIONING = 50%)

---

## E3: Backtest Engine (เครื่องมือทดสอบย้อนหลัง)

### US-3.1 — รัน backtest 20 ปีด้วย vectorbt

**As a** solo trader
**I want** ระบบรัน backtest strategy ย้อนหลัง 20 ปี (2005-2025)
**So that** ฉันรู้ว่า strategy นี้ทำงานอย่างไรในช่วงวิกฤตต่างๆ

**Acceptance Criteria:**
- [ ] Backtest ครอบคลุม: GFC 2008, dot-com recovery 2005-2006, COVID crash 2020, rate hike 2022
- [ ] ใช้ vectorbt รัน walk-forward: train 10 ปี, test 5 ปี, rolling 1 ปี
- [ ] Transaction cost model ใน backtest:
  - Bid-ask spread: 0.05% per trade
  - ETF premium/discount: ±0.1%
  - Commission: $1 per trade
- [ ] ก่อน 2006 (DBC/SLV ยังไม่มี): ใช้ GLD + USO แทน commodity allocation
- [ ] ผลลัพธ์ขั้นต่ำที่ต้องแสดง: Sharpe Ratio, Max Drawdown, Annual Return, Calmar Ratio, Win Rate
- [ ] Backtest deterministic ทุกครั้ง (fixed seed, frozen data snapshot)

---

### US-3.2 — เปรียบเทียบกับ 60/40 benchmark

**As a** solo trader
**I want** เห็น performance ของ FlowMacro เทียบกับ 60/40 benchmark ทั้ง in-sample และ out-of-sample
**So that** ฉันรู้ว่า strategy นี้ดีกว่า passive investing จริงไหม

**Acceptance Criteria:**
- [ ] 60/40 benchmark = SPY 60% + TLT 40%, rebalanced ทุกไตรมาส
- [ ] แสดง metrics ทั้ง 2 column คู่กัน: FlowMacro vs 60/40
- [ ] ถ้า out-of-sample Sharpe < 1.0 หรือ return < benchmark → warning banner ใน dashboard
- [ ] แสดง equity curve chart ทั้งสอง strategy ใน Streamlit

---

### US-3.3 — บันทึกผล backtest ลง Supabase

**As a** solo trader
**I want** ผลลัพธ์ backtest ถูกบันทึกไว้ใน database
**So that** ฉันเปรียบเทียบ backtest ระหว่าง run ได้และ trace ที่มาได้

**Acceptance Criteria:**
- [ ] บันทึกลง table `backtest_runs`: `run_id`, `run_date`, `period_start`, `period_end`, `sharpe`, `max_dd`, `annual_return`, `calmar`, `win_rate`, `benchmark_sharpe`, `benchmark_return`
- [ ] ทุก backtest run มี `run_id` เชื่อมกับ regime data ที่ใช้
- [ ] ไม่ overwrite — append ทุก run เพื่อ track history

---

## E4: Monitoring Dashboard (แดชบอร์ดตรวจสอบ)

### US-4.1 — ดู regime ปัจจุบันได้ใน 30 วินาที

**As a** solo trader
**I want** เปิด dashboard แล้วเห็น regime ปัจจุบัน + confidence ทันที
**So that** ฉันใช้เวลาน้อยที่สุดในการเข้าใจ market condition

**Acceptance Criteria:**
- [ ] หน้าแรก (above the fold) แสดง: current_regime (ขนาดใหญ่), confidence %, growth_score, inflation_score
- [ ] ใช้สีแยก regime: GOLDILOCKS=เขียว, REFLATION=เหลือง, STAGFLATION=แดง, DEFLATION=น้ำเงิน, TRANSITIONING=เทา
- [ ] แสดง "Last updated: X hours ago" และ next scheduled run
- [ ] Load เสร็จภายใน 3 วินาที (ดึงจาก Supabase cache ไม่ใช่คำนวณ real-time)

---

### US-4.2 — ดู staleness flags ของทุก indicator

**As a** solo trader
**I want** เห็นว่า indicator ตัวไหน stale และนานแค่ไหน
**So that** ฉันรู้ว่า regime ปัจจุบันมีความน่าเชื่อถือแค่ไหน

**Acceptance Criteria:**
- [ ] ตาราง indicators แสดง: ชื่อ, ค่าปัจจุบัน, percentile rank, staleness_days, สี flag (🟢🟡🔴)
- [ ] Tier 1 indicators แสดงก่อน Tier 2 และ Tier 3
- [ ] คลิก indicator row → แสดง historical chart ย้อนหลัง 1 ปี
- [ ] ถ้า Tier 1 indicator ใด stale > 14 วัน → highlight แถวนั้นด้วยสีแดง

---

### US-4.3 — ดู backtest summary และ equity curve

**As a** solo trader
**I want** เห็น backtest performance ล่าสุดเทียบกับ 60/40 benchmark
**So that** ฉัน validate ว่า strategy ยังทำงานได้ดีอยู่

**Acceptance Criteria:**
- [ ] แสดง metrics table: Sharpe, Max DD, Annual Return ทั้ง FlowMacro และ 60/40
- [ ] Equity curve chart แสดง portfolio value เทียบกัน (normalized เริ่มต้นที่ 100)
- [ ] แสดง drawdown chart แยกต่างหาก
- [ ] ระบุชัดว่าเป็น out-of-sample period ใด

---

### US-4.4 — ดู P&L เป็น THB equivalent

**As a** solo trader
**I want** เห็นมูลค่าพอร์ตเป็นทั้ง USD และ THB
**So that** ฉันเข้าใจผลตอบแทนจริงในสกุลเงินที่ฉันใช้ชีวิต

**Acceptance Criteria:**
- [ ] ดึงอัตราแลกเปลี่ยน THB/USD จาก yfinance (`THB=X`) ทุกวัน
- [ ] แสดง portfolio value ทั้ง: USD (ตัวหลัก) และ THB equivalent (reference เท่านั้น)
- [ ] หมายเหตุชัดว่า THB figure เป็น reference ไม่ใช่ accounting จริง (ไม่มี FX hedge)
- [ ] ถ้าดึง THB=X ไม่ได้ → แสดง "FX unavailable" ไม่ใช่ error

---

## E5: Scheduler & Alerting (ตัวกำหนดเวลาและการแจ้งเตือน)

### US-5.1 — รัน daily job อัตโนมัติทุกวัน 08:00 Bangkok

**As a** solo trader
**I want** ระบบดึงข้อมูลราคาและคำนวณ daily indicators อัตโนมัติทุกเช้า
**So that** ฉันไม่ต้อง trigger manual และมีข้อมูลล่าสุดเสมอเมื่อเริ่มวัน

**Acceptance Criteria:**
- [ ] GitHub Actions cron: `30 1 * * *` (01:30 UTC = 08:30 Bangkok) ครอบคลุม DST
- [ ] Job sequence: fetch prices → calculate daily indicators (SPY 200MA, Cu/Au, UUP 20MA) → update staleness → save to Supabase
- [ ] Job ต้องเสร็จภายใน 5 นาที (ถ้าเกิน → timeout alert)
- [ ] heartbeat commit ทุก 50 วัน ป้องกัน GitHub Actions auto-pause inactive repo
- [ ] ทุก run บันทึก `run_id` (UUID), `run_type=daily`, `started_at`, `finished_at`, `status`

---

### US-5.2 — รัน weekly job อัตโนมัติทุกวันศุกร์ 08:30 Bangkok

**As a** solo trader
**I want** ระบบดึง FRED data คำนวณ regime และ update dashboard อัตโนมัติทุกศุกร์
**So that** ฉันมี regime update ล่าสุดก่อนสิ้นสัปดาห์สำหรับวางแผนสัปดาห์ถัดไป

**Acceptance Criteria:**
- [ ] GitHub Actions cron: `0 2 * * 5` (02:00 UTC Friday = 09:00 Bangkok)
- [ ] Job sequence: fetch FRED → calculate percentile ranks → compute scores → classify regime → save → Gmail alert if changed
- [ ] Job เสร็จภายใน 10 นาที
- [ ] ถ้า regime เปลี่ยนจากสัปดาห์ที่แล้ว → Gmail alert พร้อม: regime ใหม่, regime เก่า, confidence, growth_score, inflation_score
- [ ] ถ้า confidence < 60% → Gmail alert ว่า "regime uncertain - confidence: X%"

---

### US-5.3 — รับ Gmail alert เมื่อ data source fail

**As a** solo trader
**I want** รับ Gmail alert ทันทีเมื่อ data source ใดล้มเหลว
**So that** ฉันรู้ว่า regime ปัจจุบันอาจคำนวณจากข้อมูลไม่ครบและควรระวัง

**Acceptance Criteria:**
- [ ] ส่ง Gmail alert เมื่อ: yfinance fail (partial หรือ total), FRED API fail, Supabase write fail
- [ ] Alert message ต้องระบุ: (1) ชื่อ data source ที่ fail, (2) indicator ที่ได้รับผลกระทบ, (3) Tier ของ indicator นั้น, (4) timestamp
- [ ] ไม่ส่ง alert ซ้ำภายใน 1 ชั่วโมงสำหรับ error เดิม (rate limiting)
- [ ] ถ้า Gmail credentials ไม่ครบ → log warning ใน GitHub Actions แต่ไม่ crash job

---

### US-5.4 — ดู run history และ health status

**As a** solo trader
**I want** เห็น history ของทุก job run และ status ของ data sources
**So that** ฉัน debug ปัญหาได้เองโดยไม่ต้อง dig ผ่าน GitHub Actions logs

**Acceptance Criteria:**
- [ ] Dashboard แสดง last 10 runs: `run_id`, `type`, `status`, `duration`, `timestamp`
- [ ] Health panel แสดง data source status: yfinance ✅/❌, FRED ✅/❌, Supabase ✅/❌, Gmail ✅/❌
- [ ] คลิก run_id → แสดง log summary ของ run นั้น (from Supabase)
- [ ] ถ้า 2 consecutive runs fail → Gmail alert พิเศษ "system health check needed"

---

## Priority Matrix (ตาราง Priority)

| User Story | Priority | Phase 1 Must? | Effort (วัน) |
|------------|----------|---------------|--------------|
| US-1.1 (ETF prices) | P0 | ✅ Yes | 2 |
| US-1.2 (FRED indicators) | P0 | ✅ Yes | 3 |
| US-1.3 (staleness) | P1 | ✅ Yes | 1 |
| US-2.1 (percentile rank) | P0 | ✅ Yes | 2 |
| US-2.2 (growth/inflation scores) | P0 | ✅ Yes | 1 |
| US-2.3 (regime + confidence) | P0 | ✅ Yes | 1 |
| US-2.4 (allocation suggestion) | P1 | ✅ Yes | 1 |
| US-3.1 (backtest 20Y) | P0 | ✅ Yes | 5 |
| US-3.2 (vs benchmark) | P0 | ✅ Yes | 1 |
| US-3.3 (save backtest) | P1 | ✅ Yes | 1 |
| US-4.1 (regime dashboard) | P0 | ✅ Yes | 3 |
| US-4.2 (staleness flags) | P1 | ✅ Yes | 1 |
| US-4.3 (backtest summary) | P1 | ✅ Yes | 2 |
| US-4.4 (THB equivalent) | P2 | Nice to have | 1 |
| US-5.1 (daily scheduler) | P0 | ✅ Yes | 2 |
| US-5.2 (weekly scheduler) | P0 | ✅ Yes | 1 |
| US-5.3 (Gmail alert on fail) | P0 | ✅ Yes | 1 |
| US-5.4 (run history) | P2 | Nice to have | 2 |

**Total estimate (P0+P1):** ~31 วัน → ภายใน 8 สัปดาห์ (Phase 1 target)

---

## Definition of Done — Phase 1 (เกณฑ์ความสำเร็จ)

Phase 1 ถือว่า done เมื่อ **ทุก** user story ที่มี Priority P0 และ P1 ผ่าน acceptance criteria ครบถ้วน และ:

- [ ] Regime detection รันจริง ≥ 1 สัปดาห์ต่อเนื่อง ไม่มี silent failure
- [ ] Backtest 20 ปีรันได้บน vectorbt แสดงผลครบทุก metric
- [ ] Dashboard load ได้ภายใน 3 วินาที และแสดงข้อมูลถูกต้อง
- [ ] GitHub Actions cron รันตรงเวลาต่อเนื่อง 2 สัปดาห์
- [ ] Gmail alert ทดสอบแล้ว (simulate failure และรับ alert จริง)

---

## Revision History (ประวัติการแก้ไข)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-05-30 | Pae | Initial draft — Phase 1 user stories ครบทุก epic |
