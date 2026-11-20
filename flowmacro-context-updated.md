# FlowMacro — Claude Code Context (Updated June 2026)

**Status:** V3 live, paper trading week 3  
**งานใหม่ที่ต้องทำ:** Dashboard improvements + ML A/B Test  
**อย่าแตะ:** Pipeline logic, ML shadow core, Supabase columns เดิม, backtest scripts

---

## 1. สถานะปัจจุบัน (อย่าแตะ)

### V3 Core — Done & Running
```
probabilities.py   → softmax regime probabilities
momentum_filter.py → dual 13W/26W cut 50%→Cash
vol_targeting.py   → covariance-based scale ≤ 1.0
rebalance.py       → 2% band + compute_trades()
allocator.py       → REGIME_WEIGHTS + blended weights
weekly.py          → pipeline Steps 1–6 + Supabase + Telegram
```

### Paper Portfolio A (current — อย่าแตะ)
```
Start:   $3,000
Now:     $2,970 (-1.0%)
Mode:    Rule-based V3 only
Week:    3 / 26
```

### ML Shadow Mode (อย่าแตะ logic)
```
Model:    XGBoost
Status:   Shadow mode — ไม่กระทบพอร์ต
Latest:   REFLATION (94.8 confidence)
Rule:     TRANSITIONING
Agreement: 67% / 3 weeks (target 70% / 26 weeks)
Graduation: December 2026
```

### Performance Baseline
```
V2B OOS Sharpe: 0.61  MaxDD: 9.0%
V3  OOS Sharpe: 1.06  MaxDD: 8.8%  ← current
V3F OOS Sharpe: 1.04  MaxDD: 8.2%
```

---

## 2. งานที่ต้องทำ — 3 กลุ่ม

---

### กลุ่ม A: ML A/B Test — Portfolio B (Priority: HIGH)

**เหตุผล:** แทนที่จะรอ ธ.ค. 2026 ตัดสินแบบ pass/fail
สร้าง virtual Portfolio B ที่ใช้ ML blend ควบคู่กันไปเลย
ได้ 26 สัปดาห์ของข้อมูลเปรียบเทียบจริง

**A.1 — สร้าง compute_ml_blended_probs()** ✅ implemented in `flowmacro/regime/probabilities.py`

```python
# API (ดูโค้ดจริงได้ใน flowmacro/regime/probabilities.py)

from flowmacro.regime.probabilities import compute_ml_blended_probs, BlendedResult

result: BlendedResult = compute_ml_blended_probs(
    rule_probs=regime_probs,     # จาก softmax ปัจจุบัน
    ml_regime="REFLATION",       # XGBoost prediction
    ml_confidence=94.8,          # 0–100
    ml_weight=0.30,              # 30% ML, 70% Rule
)

# result.blended  — ใช้สำหรับ allocation
# result.ml_raw   — ML-only vector (เก็บใน Supabase column ml_raw_probs)
# result.rule     — rule-only copy (reference)

# ตัวอย่าง:
# rule_probs = {REFL:0.31, STAG:0.28, GOLD:0.21, DEFL:0.20}
# ml_regime  = REFLATION, ml_confidence = 94.8
# ml_raw   = {REFL:0.948, STAG:0.017, GOLD:0.017, DEFL:0.017}
# blended  = {REFL:0.50,  STAG:0.20,  GOLD:0.16,  DEFL:0.14}
```

**A.2 — Supabase: สร้าง table ใหม่**

```sql
-- Portfolio B virtual tracking
CREATE TABLE IF NOT EXISTS paper_portfolio_ml (
    date            DATE PRIMARY KEY,
    ml_blend_probs  JSONB,    -- blended probabilities (ML+Rule)
    ml_raw_probs    JSONB,    -- ML probability vector
    rule_probs      JSONB,    -- Rule probability vector (reference)
    blend_weights   JSONB,    -- resulting asset weights
    portfolio_value FLOAT,
    period_return   FLOAT,
    ml_regime       TEXT,
    ml_confidence   FLOAT,
    ml_weight_used  FLOAT DEFAULT 0.30
);
```

**A.3 — weekly.py: เพิ่ม Step 6B**

```python
# ใน weekly.py หลัง Step 6 (rebalance) เพิ่ม:
# import ที่ต้องเพิ่มด้านบน:
#   from flowmacro.regime.probabilities import compute_ml_blended_probs

# Step 6B: Portfolio B (ML-assisted) — virtual only
if ml_prediction_available:
    blend_result = compute_ml_blended_probs(
        rule_probs=regime_probs,
        ml_regime=ml_regime,
        ml_confidence=ml_confidence,
        ml_weight=0.30,
    )
    portfolio_b_weights = compute_blended_weights(blend_result.blended)
    portfolio_b_weights = apply_momentum_filter(portfolio_b_weights, price_history)
    portfolio_b_weights = apply_vol_targeting(portfolio_b_weights, returns_df)
    
    # บันทึก Portfolio B ลง Supabase (ไม่ส่ง trade orders)
    supabase.table("paper_portfolio_ml").upsert({
        "date": run_date,
        "ml_blend_probs": blend_result.blended,
        "ml_raw_probs":   blend_result.ml_raw,   # ← ใช้ .ml_raw จาก BlendedResult
        "rule_probs":     blend_result.rule,
        "blend_weights":  portfolio_b_weights,
        "portfolio_value": compute_virtual_b_value(portfolio_b_weights, run_date),
        "ml_regime":      ml_regime,
        "ml_confidence":  ml_confidence,
    }).execute()
```

**A.3b — compute_virtual_b_value() — เพิ่มใน flowmacro/broker/paper_portfolio.py**

```python
_VALUE_SERIES_B = "paper_total_value_b"
_INITIAL_CASH_B = 3_000.0  # USD — เริ่มต้นเดียวกับ Portfolio A

def compute_virtual_b_value(weights: dict[str, float], today: date) -> float:
    """
    คำนวณ virtual portfolio value สำหรับ Portfolio B (ML-blend)
    ใช้ logic เดียวกับ paper_portfolio.py:
      last_value × (1 + Σ weight_i × return_i)
    
    First run → store _INITIAL_CASH_B
    Subsequent runs → read last stored value จาก Supabase แล้วคำนวณ return
    """
    try:
        value_series = read_series(_VALUE_SERIES_B, start="2020-01-01")
    except Exception:
        return _INITIAL_CASH_B

    if value_series.empty:
        upsert_series(_VALUE_SERIES_B, pd.Series(
            [_INITIAL_CASH_B], index=[pd.Timestamp(today)]
        ))
        return _INITIAL_CASH_B

    last_date  = value_series.last_valid_index()
    last_value = float(value_series.loc[last_date])

    portfolio_return = 0.0
    for ticker, w in weights.items():
        p0 = _price_on(ticker, last_date.date())
        p1 = _price_on(ticker, today)
        if p0 and p1 and p0 > 0:
            portfolio_return += w * ((p1 / p0) - 1)

    new_value = last_value * (1 + portfolio_return)
    upsert_series(_VALUE_SERIES_B, pd.Series([new_value], index=[pd.Timestamp(today)]))
    return new_value
```

**A.4 — Dashboard: หน้า A/B Comparison**

```python
# หน้าใหม่ใน app.py หรือ pages/ab_test.py

st.title("ML A/B Test — Portfolio A vs B")
st.caption("A = Rule-only V3 | B = V3 + ML blend (30%)")

# Equity curve ทั้งคู่
fig = go.Figure()
fig.add_trace(go.Scatter(y=portfolio_a_values, name="A: Rule-only"))
fig.add_trace(go.Scatter(y=portfolio_b_values, name="B: ML-blend"))
st.plotly_chart(fig)

# Metrics comparison
col1, col2, col3 = st.columns(3)
col1.metric("Sharpe A", f"{sharpe_a:.2f}")
col2.metric("Sharpe B", f"{sharpe_b:.2f}", f"{sharpe_b-sharpe_a:+.2f}")
col3.metric("Weeks tracked", f"{weeks}/26")

# Agreement between A and B
st.metric("A vs B Agreement", f"{ab_agreement:.0f}%",
          help="% สัปดาห์ที่ทั้งคู่ตัดสินใจ rebalance ตรงกัน")
```

---

### กลุ่ม B: Dashboard UX Fixes (Priority: HIGH)

**B.1 — Action Banner บนสุดทุกหน้า**

```python
def render_action_banner(signal_strength, days_to_rebalance, conviction):
    if signal_strength == "WEAK" or conviction <= 3:
        st.error("🔴 HOLD — ไม่ต้องทำอะไร | สัญญาณอ่อน รอสัปดาห์หน้า")
    elif days_to_rebalance == 0:
        st.warning("🟡 REBALANCE TODAY — ดู trades list ด้านล่าง")
    else:
        st.success(f"🟢 HOLD — Rebalance ใน {days_to_rebalance} วัน")
```

**B.2 — Regime badge แสดง confidence**

```python
dominant_prob = max(regime_probs.values())
dominant_regime = max(regime_probs, key=regime_probs.get)

if dominant_prob >= 0.60:
    label, color = dominant_regime, REGIME_COLORS[dominant_regime]
elif dominant_prob >= 0.40:
    label, color = f"{dominant_regime} (MODERATE)", "orange"
else:
    label, color = "TRANSITIONING", "gray"
# ตอนนี้ควรแสดง TRANSITIONING (prob สูงสุดแค่ 31%)
```

**B.3 — Arrow bug ใน Backtest page** ✅ แก้แล้ว (commit d745155) — `2_backtest.py` ใช้ delta คำนวณจากตัวเลขจริงอยู่แล้ว ไม่ต้องทำซ้ำ

**B.4 — VIX threshold** ✅ แก้แล้วใน dashboard redesign — `app.py:565` ใช้ `< 25 → "ปกติ"` และ `> 35 → "วิกฤต"` ถูกต้องแล้ว ไม่ต้องทำซ้ำ

**B.5 — Label V2B ในหน้า backtest**

```python
st.warning("⚠️ แสดงผล V2B (legacy ก่อน V3 upgrade มิ.ย. 2026) "
           "— V3 results ดูที่ Walk-Forward tab")
```

---

### กลุ่ม C: Portfolio Performance Section (Priority: MEDIUM)

**C.1 — Return table เทียบ benchmark**

```python
# ดึง portfolio_value จาก paper_portfolio และ paper_portfolio_ml
# ดึง benchmark returns จาก yfinance (SPY, AGG สำหรับ 60/40)

periods = {"YTD": "2026-01-01", "1M": "-30d", "3M": "-90d"}

for period_label, since in periods.items():
    fm_ret  = calc_return("paper_portfolio", since)
    bm_ret  = calc_return("60/40", since)
    spy_ret = calc_return("SPY", since)
    
    # ถ้า live data ไม่ครบ period → ใช้ backtest_v3.csv แทน
    # ระบุชัด: "(backtest)" หรือ "(live)"
```

**C.2 — Position P&L card**

```python
# แสดง weight + P&L แต่ละ asset
for asset, weight in current_blend.items():
    if asset == "Cash": continue
    pnl = get_pnl(asset)  # จาก paper_positions table
    color = "green" if pnl > 0 else "red"
    st.markdown(f"{asset}: {weight:.1%} | {pnl:+.1f}%")
```

**C.3 — Expected return box**

```python
st.info("""
📊 ผลตอบแทนคาดหวัง (จาก Walk-Forward backtest V3 — 11 windows)
Conservative  Sharpe 0.7  →  ~10%/ปี
Base case     Sharpe 1.0  →  ~14%/ปี
Good case     Sharpe 1.3  →  ~17%/ปี
MaxDD คาดหวัง ≤ 12%
⚠️ ประมาณการจาก backtest ไม่ใช่การรับประกัน
""")
```

**C.4 — Data Quality indicator**

```python
# เช็ค updated_at ของแต่ละ indicator ใน Supabase
FRESHNESS_DAYS = {"GDP": 95, "CPI": 35, "Fed Funds": 10, "Yield Curve": 3}

fresh_count = sum(
    1 for ind in indicators
    if (today - last_updated[ind]).days <= FRESHNESS_DAYS[ind]
)
score = fresh_count / len(indicators) * 100

if score >= 90: st.success(f"✅ Data Quality: {score:.0f}%")
elif score >= 70: st.warning(f"⚠️ Data Quality: {score:.0f}% — บาง indicator stale")
else: st.error(f"❌ Data Quality: {score:.0f}% — ผล regime อาจไม่น่าเชื่อถือ")
```

---

## 3. Implementation Order

```
Step 1  ✅ DONE    B.4 VIX threshold (แก้แล้วใน dashboard redesign)
Step 2  ✅ DONE    B.2 Regime badge confidence (app.py:511–530)
Step 3  ✅ DONE    B.1 Action Banner (app.py:457–465)
Step 4  ✅ DONE    B.5 V2B label (2_backtest.py:126)
Step 5  ✅ DONE    A.1 compute_ml_blended_probs() + BlendedResult + 10 tests
Step 6  ✅ DONE    A.2 Supabase table paper_portfolio_ml (SQL + store.py functions)
Step 7  ✅ DONE    A.3b compute_virtual_b_value() ใน paper_portfolio.py (4 tests)
Step 8  ✅ DONE    A.3 weekly.py Step 6B (weekly.py:217–267)
Step 9  ✅ DONE    A.4 Dashboard A/B Comparison page (pages/6_ab_test.py)
Step 10 ✅ DONE    C.4 Data Quality indicator (app.py:979–993)
Step 11 ✅ DONE    C.1 Return table + C.2 Position P&L (5_paper_trading.py)
Step 12 ✅ DONE    C.3 Expected return box (5_paper_trading.py)
```

---

## 4. Constraints (ห้ามแตะเด็ดขาด)

```
❌ weekly.py Steps 1–6 (pipeline core)
❌ ML shadow mode training / XGBoost model
❌ Supabase columns ที่มีอยู่แล้ว (เพิ่มได้ อย่าลบ)
❌ backtest_v3.py และ CSV files
❌ paper_portfolio table (Portfolio A — อย่าแตะ records)
❌ graduation criteria logic

✅ app.py (Streamlit) — แก้และเพิ่มได้เต็มที่
✅ pages/ — เพิ่มหน้าใหม่ได้
✅ flowmacro/regime/probabilities.py — เพิ่ม function ใหม่ได้
✅ flowmacro/scheduler/weekly.py — เพิ่ม Step 6B ท้ายเท่านั้น
✅ Supabase — เพิ่ม table ใหม่ได้
✅ tests/ — เพิ่ม tests ให้ครอบคลุม functions ใหม่
```

---

## 5. Tests ที่ต้องเพิ่ม

### A.1 tests ✅ DONE — `tests/regime/test_regime_probabilities.py` (10 tests, 23 total pass)

ครอบคลุม:
- `BlendedResult` named tuple มีครบ 3 fields (blended, ml_raw, rule)
- blended + ml_raw sum to 1.0
- ml_weight=0 → blended == rule_probs
- ml_weight=1 → blended == ml_raw
- ml_raw concentration ถูกต้อง (confidence บน predicted regime, remaining แบ่งเท่ากัน)
- dominant regime skews toward ML เมื่อ ml_weight > 0
- invalid regime/confidence raises ValueError
- rule dict เป็น copy ไม่ใช่ reference (mutation guard)

### Tests ที่ยังต้องเพิ่ม (เมื่อ implement งานถัดไป)

```python
# A.3b: compute_virtual_b_value()
def test_virtual_b_init_returns_initial_cash():
    # first run → return 3000.0

def test_virtual_b_subsequent_run_uses_price_change():
    # week 2 → last_value × (1 + weighted_return)

# A.3: weekly.py Step 6B (integration test)
def test_step6b_skipped_when_ml_unavailable():
    # ml_prediction_available=False → paper_portfolio_ml not written
```

---

## 6. Key Decisions ที่ตกลงแล้ว

| Decision | ค่า | เหตุผล |
|----------|-----|--------|
| ML weight | 0.30 | เริ่มต้น conservative ปรับได้ทีหลัง |
| Portfolio B | Virtual เท่านั้น | ไม่ risk Portfolio A ที่รันจริง |
| ML → prob vector | distribute remaining equally | Simple, fair |
| Graduation deadline | ธ.ค. 2026 | ยังคงเดิม แต่มีข้อมูล 26W จริงประกอบ |
| A/B comparison metric | Sharpe + MaxDD + Agreement | ครอบคลุม risk-adjusted return |
