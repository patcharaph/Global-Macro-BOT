# FlowMacro — XGBoost Feature Expansion (v3)
# ทำหลัง graduation ธ.ค. 2026 เท่านั้น — ห้ามแตะระหว่าง evaluation period

---

## Context

XGBoost shadow model ปัจจุบัน:
- Features: 17 ตัว (lagging/coincident ทั้งหมด)
- Training data: 712 สัปดาห์
- Walk-Forward Accuracy: 66.3% (72% ex-COVID)
- NBER validation: 5/6
- Status: Shadow mode, graduation ธ.ค. 2026

จุดอ่อนหลัก:
1. Features ส่วนใหญ่เป็น Lagging Indicators (GDP ช้า 3 เดือน, CPI ช้า 4-6 สัปดาห์)
2. ไม่มี Price-based Leading Indicators — ตลาดนำเศรษฐกิจ 6-12 เดือน
3. ขาด Credit Cycle signal
4. ไม่มี Global demand (ดูแค่ US)
→ COVID problem: ตลาดร่วง ก.พ. 2020 แต่ model รู้ช้าไป 3 เดือน

เป้าหมายหลัง retrain: accuracy > 72% (ดีกว่า ex-COVID ปัจจุบัน)

---

## Features ทั้งหมดที่จะมี (31 ตัว)

### กลุ่ม 1 — Macro Indicators เดิม 17 ตัว (อย่าลบ)

```python
MACRO_FEATURES = [
    # Growth (Percentile Rank 260W Rolling Window)
    "gdp_growth_pr",
    "industrial_production_pr",
    "retail_sales_pr",
    "ism_manufacturing_pr",
    "ism_services_pr",
    "unemployment_pr",
    "initial_jobless_claims_pr",

    # Inflation (Percentile Rank 260W Rolling Window)
    "cpi_pr",
    "ppi_pr",
    "core_pce_pr",

    # Derived scores
    "growth_score",           # Weighted Average growth indicators
    "inflation_score",        # Weighted Average inflation indicators
    "growth_momentum_4w",     # growth_score delta vs 4W ago
    "inflation_momentum_4w",  # inflation_score delta vs 4W ago

    # Market sentiment
    "vix",
    "cot_gold_net",           # COT Non-Commercial net position
    "cot_oil_net",
]
```

---

### กลุ่ม 2 — Macro Leading Indicators ใหม่ 5 ตัว

```python
# Feature 1: HY Credit Spread
# FRED: BAMLH0A0HYM2
# เหตุผล: financial stress / credit cycle — นำหน้า recession 6-12 เดือน
"hy_spread_pr"              # Percentile Rank 260W

# Feature 2: TIPS Breakeven Inflation 5Y
# FRED: T5YIE
# เหตุผล: market inflation expectation (forward-looking vs CPI ที่ lagging)
"tips_breakeven_5y_pr"      # Percentile Rank 260W

# Feature 3: China Manufacturing PMI
# FRED: CPMINDXM → resample weekly + ffill
# เหตุผล: China = demand engine หลักของ commodities (DBC, EEM)
"china_pmi_pr"              # Percentile Rank 260W

# Feature 4: Copper/Gold Ratio
# yfinance: HG=F / GC=F (Friday close)
# เหตุผล: industrial cycle indicator (Dr. Copper)
"copper_gold_ratio_pr"      # Percentile Rank 260W

# Feature 5: Policy Forward Signal
# FRED: DGS1 - FEDFUNDS (1Y Treasury - Fed Funds Rate)
# เหตุผล: market expectation ว่า Fed จะขึ้น/ลดดอกเบี้ย
"policy_forward_signal_pr"  # Percentile Rank 260W
```

---

### กลุ่ม 3 — Price-Based Leading Indicators ใหม่ 9 ตัว

```python
# หมายเหตุสำคัญ:
# Price features ใช้สำหรับ REGIME DETECTION เท่านั้น
# ไม่ใช้ตัดสินซื้อขาย asset โดยตรง (ป้องกัน circular logic)
# ต่างจาก Momentum Filter (Layer 3) ที่ใช้สำหรับ position sizing

# --- Equity momentum — นำเศรษฐกิจ 6-12 เดือน ---

# Feature 6: SPY 26W return
# yfinance: SPY (Friday close)
# เหตุผล: ตลาดหุ้นนำ GDP 6-12 เดือน
"spy_return_26w"            # (price_now / price_26w_ago) - 1, Percentile Rank 260W

# Feature 7: SPY 52W return
# เหตุผล: long-term equity trend บอก structural regime shift
"spy_return_52w"            # Percentile Rank 260W

# Feature 8: EEM 26W return
# yfinance: EEM
# เหตุผล: EM equity นำ global growth cycle + commodity demand
"eem_return_26w"            # Percentile Rank 260W

# --- Bond momentum — นำ Fed policy 3-6 เดือน ---

# Feature 9: TLT 13W return
# yfinance: TLT
# เหตุผล: bond rally = deflation/recession coming
# COVID: TLT +8% ใน 4 สัปดาห์ ก่อน GDP ยืนยัน recession
"tlt_return_13w"            # Percentile Rank 260W

# Feature 10: Yield curve momentum (rate of change)
# FRED: DGS10 - DGS2 (10Y-2Y spread delta vs 4W ago)
# เหตุผล: ทิศทางการเปลี่ยน yield curve สำคัญกว่า level
"yield_curve_momentum_4w"   # raw delta (basis points per week)

# --- Dollar — นำ global macro cycle ---

# Feature 11: DXY 13W return
# yfinance: DX-Y.NYB
# เหตุผล: dollar แข็ง = risk-off / deflation pressure
#          dollar อ่อน = reflation / EM/commodity bullish
"dxy_return_13w"            # Percentile Rank 260W

# --- Commodity — นำ inflation 2-3 เดือน ---

# Feature 12: DBC 13W return
# yfinance: DBC
# เหตุผล: commodity surge → inflation regime coming
"dbc_return_13w"            # Percentile Rank 260W

# Feature 13: GLD 13W return
# yfinance: GLD
# เหตุผล: gold leads inflation expectations
"gld_return_13w"            # Percentile Rank 260W

# Feature 14: HY Spread momentum (rate of change)
# FRED: BAMLH0A0HYM2 delta vs 4W ago
# เหตุผล: spread กำลังขยาย = stress เพิ่ม (leading signal กว่า level)
"hy_spread_momentum_4w"     # raw delta (%)
```

---

## Fetch Functions

```python
# flowmacro/data/features_v2.py

import yfinance as yf
import pandas as pd
import numpy as np
from fredapi import Fred

fred = Fred(api_key=FRED_API_KEY)

def percentile_rank(series: pd.Series, window: int = 260) -> pd.Series:
    """Rolling Percentile Rank — เหมือน features เดิม"""
    return series.rolling(window).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1]
    )

def fetch_price_return(ticker: str, weeks: int, start: str, end: str) -> pd.Series:
    """ดึง price return N สัปดาห์ แล้วแปลงเป็น Percentile Rank"""
    prices = yf.download(ticker, start=start, end=end, progress=False)["Close"]
    prices = prices.resample("W-FRI").last()
    returns = prices.pct_change(periods=weeks)
    return percentile_rank(returns, window=260)

def fetch_fred_momentum(series_id: str, weeks: int, start: str, end: str) -> pd.Series:
    """ดึง FRED series แล้วคำนวณ momentum (delta)"""
    series = fred.get_series(series_id, start, end)
    series_weekly = series.resample("W-FRI").last().ffill()
    return series_weekly.diff(periods=weeks)

# ตัวอย่าง fetch ทุก feature ใหม่
def build_features_v2(start: str, end: str) -> pd.DataFrame:
    df = pd.DataFrame()

    # Macro Leading (กลุ่ม 2)
    df["hy_spread_pr"]              = percentile_rank(
        fred.get_series("BAMLH0A0HYM2", start, end)
            .resample("W-FRI").last().ffill()
    )
    df["tips_breakeven_5y_pr"]      = percentile_rank(
        fred.get_series("T5YIE", start, end)
            .resample("W-FRI").last().ffill()
    )
    df["china_pmi_pr"]              = percentile_rank(
        fred.get_series("CPMINDXM", start, end)
            .resample("W-FRI").last().ffill()
    )
    copper = yf.download("HG=F", start, end)["Close"].resample("W-FRI").last()
    gold   = yf.download("GC=F", start, end)["Close"].resample("W-FRI").last()
    df["copper_gold_ratio_pr"]      = percentile_rank(copper / gold)

    t1y = fred.get_series("DGS1", start, end).resample("W-FRI").last().ffill()
    ffr = fred.get_series("FEDFUNDS", start, end).resample("W-FRI").last().ffill()
    df["policy_forward_signal_pr"]  = percentile_rank(t1y - ffr)

    # Price Leading (กลุ่ม 3)
    df["spy_return_26w"]            = fetch_price_return("SPY",      26, start, end)
    df["spy_return_52w"]            = fetch_price_return("SPY",      52, start, end)
    df["eem_return_26w"]            = fetch_price_return("EEM",      26, start, end)
    df["tlt_return_13w"]            = fetch_price_return("TLT",      13, start, end)
    df["dxy_return_13w"]            = fetch_price_return("DX-Y.NYB", 13, start, end)
    df["dbc_return_13w"]            = fetch_price_return("DBC",      13, start, end)
    df["gld_return_13w"]            = fetch_price_return("GLD",      13, start, end)

    t10 = fred.get_series("DGS10", start, end).resample("W-FRI").last().ffill()
    t2  = fred.get_series("DGS2",  start, end).resample("W-FRI").last().ffill()
    df["yield_curve_momentum_4w"]   = (t10 - t2).diff(4)

    hy  = fred.get_series("BAMLH0A0HYM2", start, end).resample("W-FRI").last().ffill()
    df["hy_spread_momentum_4w"]     = hy.diff(4)

    return df.dropna()
```

---

## Ratio Check

```python
TOTAL_FEATURES   = 17 + 5 + 9   # = 31
TRAINING_WEEKS   = 712           # จะเพิ่มขึ้นเมื่อถึง ธ.ค. 2026

ratio = TRAINING_WEEKS / TOTAL_FEATURES
# 712 / 31 = 22.97 : 1  ← ผ่านเกณฑ์ขั้นต่ำ 20:1

# ถ้าต้องการ safety margin มากขึ้น:
# ทำ Feature Importance ก่อน ตัด features ที่ importance < 0.01 ออก
# เป้าหมาย: ratio > 25:1 หลังตัด redundant features
```

---

## Feature Importance Check (ทำก่อน retrain)

```python
import shap

# Step 1: วัด SHAP values บน model ปัจจุบัน (17 features)
explainer   = shap.TreeExplainer(current_model)
shap_values = explainer.shap_values(X_train)
importance  = pd.DataFrame({
    "feature":    CURRENT_FEATURES,
    "shap_mean":  np.abs(shap_values).mean(axis=0)
}).sort_values("shap_mean", ascending=False)

# Step 2: ตัด features ที่ shap_mean < 0.01 ออก
low_importance = importance[importance["shap_mean"] < 0.01]["feature"].tolist()
# เช่น ถ้า PPI กับ CPI overlap กันมาก → ตัด PPI ออก

# Step 3: เพิ่ม 14 features ใหม่แทน
# Target: final feature count ให้ ratio > 25:1
```

---

## Supabase Schema

```sql
CREATE TABLE IF NOT EXISTS macro_features_v2 (
    date DATE PRIMARY KEY,

    -- กลุ่ม 1: Macro เดิม 17 ตัว
    gdp_growth_pr               FLOAT,
    industrial_production_pr    FLOAT,
    retail_sales_pr             FLOAT,
    ism_manufacturing_pr        FLOAT,
    ism_services_pr             FLOAT,
    unemployment_pr             FLOAT,
    initial_jobless_claims_pr   FLOAT,
    cpi_pr                      FLOAT,
    ppi_pr                      FLOAT,
    core_pce_pr                 FLOAT,
    growth_score                FLOAT,
    inflation_score             FLOAT,
    growth_momentum_4w          FLOAT,
    inflation_momentum_4w       FLOAT,
    vix                         FLOAT,
    cot_gold_net                FLOAT,
    cot_oil_net                 FLOAT,

    -- กลุ่ม 2: Macro Leading ใหม่ 5 ตัว
    hy_spread_pr                FLOAT,
    tips_breakeven_5y_pr        FLOAT,
    china_pmi_pr                FLOAT,
    copper_gold_ratio_pr        FLOAT,
    policy_forward_signal_pr    FLOAT,

    -- กลุ่ม 3: Price Leading ใหม่ 9 ตัว
    spy_return_26w              FLOAT,
    spy_return_52w              FLOAT,
    eem_return_26w              FLOAT,
    tlt_return_13w              FLOAT,
    yield_curve_momentum_4w     FLOAT,
    dxy_return_13w              FLOAT,
    dbc_return_13w              FLOAT,
    gld_return_13w              FLOAT,
    hy_spread_momentum_4w       FLOAT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Implementation Steps

```
ทำได้ก่อน ธ.ค. 2026 (เตรียม data):
  Step 1: Feature importance SHAP บน model ปัจจุบัน
          → ระบุ features ที่ redundant / ไม่มีประโยชน์
  Step 2: สร้าง build_features_v2() ใน features_v2.py
  Step 3: Backfill historical data 712+ สัปดาห์
          → บันทึกลง Supabase: macro_features_v2
  Step 4: เพิ่ม weekly fetch ใน pipeline (ดึงข้อมูลใหม่ทุกสัปดาห์)
          แต่ยังไม่ใช้ train model

ทำหลัง graduation ธ.ค. 2026 เท่านั้น:
  Step 5: ตัด low-importance features ออก (จาก Step 1)
  Step 6: Retrain XGBoost ด้วย features ใหม่
  Step 7: Walk-Forward validate
  Step 8: ถ้า accuracy > 66.3% → deploy ใน shadow mode ต่อ
```

---

## Acceptance Criteria

```
✅ fetch ครบ 712+ สัปดาห์ ทุก feature ใหม่
✅ NaN < 5% ต่อ feature (forward fill สำหรับ monthly data)
✅ Sample-to-feature ratio ≥ 20:1 (target > 25:1)
✅ Walk-Forward OOS accuracy ≥ 66.3%
✅ COVID period accuracy ดีขึ้น (price features ควรช่วย)
✅ NBER validation ยังผ่าน ≥ 5/6
✅ Unit tests ทุก fetch function
```

---

## Constraints

```
❌ ห้าม retrain ก่อน ธ.ค. 2026
❌ ห้ามแตะ XGBoost model ที่รันอยู่ปัจจุบัน
❌ ห้าม deploy model ใหม่โดยไม่ผ่าน Walk-Forward
❌ ห้ามลบ features เดิม 17 ตัว
❌ ห้ามใช้ price return ของ asset ที่ถืออยู่ เป็น signal ซื้อขายตรงๆ
   (circular logic — ใช้ได้แค่สำหรับ regime detection)

✅ เตรียม code + backfill data ได้เลยตอนนี้
✅ เพิ่ม fetch ใน weekly pipeline ได้ (เก็บข้อมูล ยังไม่ใช้ train)
✅ Step 1-4 ทำก่อน ธ.ค. 2026 ได้
```

---

## Note สำหรับ Claude Code

- ทุก FRED series → `percentile_rank(series, window=260)` ก่อนเสมอ
- Price returns → คำนวณ return ก่อน แล้วค่อย percentile_rank
- Momentum features (4W delta) → ไม่ต้อง percentile_rank ใช้ raw delta
- China PMI, monthly data → `resample("W-FRI").last().ffill()`
- ถ้า FRED API ไม่มี series → log warning + skip (อย่า raise exception)
- ถ้า yfinance timeout → retry 3 ครั้ง แล้ว fallback ใช้ค่าสัปดาห์ก่อน
