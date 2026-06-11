# FlowMacro V3 — PRD & Context Summary for Claude Code

**Version:** 3.0 Draft  
**Date:** June 2026  
**Status:** Ready for implementation  
**Target:** Claude Code — implement V3 changes on top of existing V2B codebase

---

## 1. Project Overview (ภาพรวม)

**FlowMacro** คือ personal algorithmic trading system สำหรับ systematic global macro
position trading ด้วยตัวเอง (personal use only) ไม่ใช่ commercial product

- **Holding period:** 1–3 เดือน
- **Universe:** Global multi-asset ETFs + spot crypto
- **Target broker:** IBKR Singapore (Phase 4, ยังไม่ live)
- **ปัจจุบัน:** Paper trading live ตั้งแต่ต้น June 2026 + ML shadow mode

---

## 2. Current State — V2B (สิ่งที่มีอยู่แล้ว อย่าแตะ)

### 2.1 Regime Framework
- **4 regimes:** Goldilocks, Reflation, Stagflation, Deflation
- **Transitioning state:** SHY 25% + GLD 25% + Cash 50%
- **Switching logic:** Hard classification — เมื่อ confidence > 15% entry / < 20% exit (Hysteresis Band)
- **Confidence formula:** `(2×|growth−50| + 2×|inflation−50|) / 2`

### 2.2 Macro Score Engine
- **11 indicators** ใน 3 tiers (weighted 50% / 30% / 20%)
- **Growth score & inflation score:** Percentile Rank บน Rolling Window 5 ปี (260 สัปดาห์)
- **Data source:** FRED API
- **Inverse transformation** สำหรับ indicators ที่ค่าสูง = signal อ่อน

### 2.3 Current Regime Allocations (V2B — Base weights ที่ใช้อยู่)

| Regime | Allocations | Cash buffer |
|--------|-------------|-------------|
| GOLDILOCKS | SPY 24%, QQQ 16%, IWM 12%, EFA 12%, EEM 8%, BTC-USD 8% | 20% |
| REFLATION | SPY 16%, IWM 8%, EEM 16%, GLD 16%, DBC 16%, USO 8% | 20% |
| STAGFLATION | GLD 30%, SLV 15%, DBC 20%, UUP 15% | 20% |
| DEFLATION | TLT 40%, IEF 25%, UUP 15% | 20% |

### 2.4 Tech Stack (คงเดิมทั้งหมด)

```
Data:          FRED API (macro indicators), yfinance (price data)
Database:      Supabase (PostgreSQL)
ML:            XGBoost (shadow mode — อย่าแตะ)
Backtesting:   vectorbt + Walk-Forward Analysis (train 10Y / test 5Y / roll 1Y)
Scheduling:    GitHub Actions (weekly run)
Dashboard:     Streamlit Cloud (5 pages)
Logging:       structlog (JSON, structured, run_id binding)
Alerts:        Telegram bot
AI thesis:     OpenRouter API
Portfolio opt: Riskfolio-Lib (available แต่ยังไม่ใช้ใน production)
```

### 2.5 Current Performance (V2B Baseline)
- **Backtest Sharpe Ratio:** 0.60
- **OOS Sharpe (Walk-Forward):** 0.80
- **Max Drawdown:** 16.8%
- **Tests:** 76 tests passing, 0 failures

### 2.6 ML Shadow Mode (อย่าแตะ)
- XGBoost trained บน 712 weeks, 17 features
- Walk-forward accuracy ~66%
- **Graduation evaluation:** December 2026
- Criteria: agreement ≥70%, Sharpe ML >0.40, NBER ≥5/6

---

## 3. V3 Changes — สิ่งที่ต้องสร้างใหม่

> **หลักการ:** เพิ่มทีละ layer แล้ว backtest Walk-Forward ก่อน deploy แต่ละ layer
> กฎเหล็ก: layer ไหน OOS Sharpe ไม่ดีขึ้น ≥0.05 → ตัดทิ้ง

### 3.1 แก้ Base Weights ต่อ Regime (Priority: HIGH — ทำก่อน)

แก้ constants ใน allocation config โดยตรง:

```python
REGIME_WEIGHTS = {
    "GOLDILOCKS": {
        "SPY": 0.20, "QQQ": 0.16, "IWM": 0.12,
        "EFA": 0.12, "EEM": 0.13, "BTC-USD": 0.07,
        # รวม investable = 80%, cash buffer = 20%
    },
    "REFLATION": {
        "SPY": 0.12, "IWM": 0.08, "EEM": 0.20,
        "GLD": 0.10, "DBC": 0.30,
        # ลบ USO ออก (contango/roll cost), DBC absorbs energy exposure
    },
    "STAGFLATION": {
        "GLD": 0.34, "SLV": 0.08, "DBC": 0.24, "UUP": 0.14,
        # ลด SLV (ρ≈0.82 กับ GLD + industrial demand), เพิ่ม GLD+DBC
    },
    "DEFLATION": {
        "TLT": 0.30, "IEF": 0.25, "UUP": 0.15, "SHY": 0.10,
        # ลด TLT (Modified Duration ≈17yr risk), เพิ่ม SHY เป็น short-end anchor
    },
    "TRANSITIONING": {
        "SHY": 0.25, "GLD": 0.25,
        # cash 50% (คงเดิม)
    },
}
CASH_BUFFER = 0.20  # permanent, ทุก regime
```

เหตุผลที่แก้แต่ละ asset มีอยู่ใน session context ด้านบน

---

### 3.2 Softmax Regime Probabilities (Priority: HIGH)

**แทนที่ hard classification** ด้วย probability distribution — นี่คือการเปลี่ยนแปลงที่ใหญ่ที่สุด

**ปัญหาของ V2B hard switch:** regime เปลี่ยนทีเดียว → turnover สูง + whipsaw + ขายผิดจังหวะ

**V3 logic:**

```python
import numpy as np

# Centroids ในพื้นที่ (growth_score, inflation_score)
REGIME_CENTROIDS = {
    "GOLDILOCKS":  (75, 25),
    "REFLATION":   (75, 75),
    "STAGFLATION": (25, 75),
    "DEFLATION":   (25, 25),
}

def compute_regime_probabilities(
    growth_score: float,      # 0–100, Percentile Rank
    inflation_score: float,   # 0–100, Percentile Rank
    tau: float = 20.0,        # temperature: ต่ำ=เด็ดขาด, สูง=blend มาก
) -> dict[str, float]:
    """
    คำนวณ Euclidean Distance จาก current point ไปยัง centroid ของแต่ละ regime
    แปลงเป็น probability ด้วย Softmax Function
    
    ผลพลอยได้: Transitioning state และ Hysteresis Band หายไปเองโดยธรรมชาติ
    เมื่อสัญญาณก้ำกึ่ง → entropy สูง → portfolio blend หลาย regime เองอัตโนมัติ
    """
    distances = {
        regime: np.hypot(growth_score - g, inflation_score - i)
        for regime, (g, i) in REGIME_CENTROIDS.items()
    }
    # Softmax บน negative distance (ใกล้ centroid มาก = probability สูง)
    exp_scores = {r: np.exp(-d / tau) for r, d in distances.items()}
    total = sum(exp_scores.values())
    probs = {r: v / total for r, v in exp_scores.items()}
    
    # log ด้วย structlog ทุกครั้ง
    return probs
```

**Tau calibration:** ทดสอบ tau = 15, 20, 25 ผ่าน Walk-Forward Analysis แล้วเลือกที่ให้ OOS Sharpe ดีที่สุด

---

### 3.3 Probability-Weighted Blended Allocation (Priority: HIGH)

ใช้ probabilities จาก 3.2 เพื่อ blend weights ของทุก regime

```python
def compute_blended_weights(
    regime_probs: dict[str, float],
    regime_weights: dict[str, dict[str, float]],
) -> dict[str, float]:
    """
    Weighted Average ของ allocations ทุก regime ถ่วงด้วย Softmax probabilities
    
    Formula: w_asset = Σ_k ( p_k × w_k_asset )
    
    ผลลัพธ์: เมื่อ probability ค่อยๆ เลื่อน พอร์ตค่อยๆ ไหลตาม
    → turnover ลดลงมากเมื่อเทียบกับ hard switch
    """
    all_assets = set()
    for weights in regime_weights.values():
        all_assets.update(weights.keys())
    
    blended = {}
    for asset in all_assets:
        blended[asset] = sum(
            regime_probs.get(regime, 0) * regime_weights.get(regime, {}).get(asset, 0)
            for regime in regime_weights
        )
    
    # ตรวจว่า investable sum ≈ 80% (cash = 20% คงที่)
    investable = sum(v for k, v in blended.items() if k != "Cash")
    assert abs(investable - 0.80) < 0.01, f"Investable sum error: {investable}"
    
    return blended
```

---

### 3.4 Dual Momentum Filter (Priority: MEDIUM)

```python
def apply_momentum_filter(
    weights: dict[str, float],
    price_history: pd.DataFrame,   # weekly close prices, columns = assets
    window_fast: int = 13,         # 13 weeks ≈ 3 months
    window_slow: int = 26,         # 26 weeks ≈ 6 months
    threshold: float = -0.05,      # -5% trigger
) -> dict[str, float]:
    """
    Dual confirmation: ทั้ง 13W และ 26W ต้องติดลบพร้อมกัน จึงลด weight
    เหตุผล: single window เกิด false positive สูงในช่วง volatile sideways
    
    Rolling Window autocorrelation: assets ที่ downtrend มักลงต่อ (Jegadeesh & Titman 1993)
    """
    filtered = weights.copy()
    freed_weight = 0.0
    
    for asset, weight in weights.items():
        if asset == "Cash" or asset not in price_history.columns:
            continue
        
        prices = price_history[asset].dropna()
        if len(prices) < window_slow:
            continue
        
        mom_fast = (prices.iloc[-1] / prices.iloc[-window_fast] - 1)
        mom_slow = (prices.iloc[-1] / prices.iloc[-window_slow] - 1)
        
        # ต้องติดลบทั้งคู่ (dual confirmation)
        if mom_fast < threshold and mom_slow < threshold:
            cut = weight * 0.50
            filtered[asset] = weight - cut
            freed_weight += cut
            # log: asset, mom_fast, mom_slow, weight_before, weight_after
    
    # freed weight ไป cash (ไม่ redistribute ไป asset อื่น)
    filtered["Cash"] = filtered.get("Cash", 0) + freed_weight
    
    return filtered
```

---

### 3.5 Portfolio-Level Volatility Targeting (Priority: MEDIUM)

```python
def apply_vol_targeting(
    weights: dict[str, float],
    returns_df: pd.DataFrame,      # weekly returns, columns = assets
    target_vol: float = 0.10,      # 10% annualized target
    window: int = 26,              # Rolling Window 26 weeks
    max_scale: float = 1.0,        # ไม่ใช้ leverage
) -> dict[str, float]:
    """
    Scale portfolio exposure ตาม realized volatility
    ใช้ Covariance Matrix (ไม่ใช่แค่ individual σ) → จับ correlation spikes ได้
    
    อ้างอิง: Moreira & Muir (2017) 'Volatility-Managed Portfolios', JoF
    """
    # assets ที่ invest (ไม่รวม Cash)
    invest_assets = [a for a in weights if a != "Cash" and a in returns_df.columns]
    w_vec = np.array([weights[a] for a in invest_assets])
    
    # Covariance Matrix บน rolling window, annualize (×52 สัปดาห์)
    cov_matrix = returns_df[invest_assets].tail(window).cov() * 52
    
    # Portfolio volatility = √(wᵀΣw)
    port_vol = np.sqrt(w_vec @ cov_matrix.values @ w_vec)
    
    if port_vol <= 0:
        return weights
    
    # Scale factor: ลด exposure ตอน vol สูง, ไม่เพิ่มตอน vol ต่ำ (no leverage)
    scale = min(max_scale, target_vol / port_vol)
    
    scaled = {}
    total_scaled = 0.0
    for asset in invest_assets:
        scaled[asset] = weights[asset] * scale
        total_scaled += scaled[asset]
    
    scaled["Cash"] = 1.0 - total_scaled
    
    # log: port_vol, scale_factor, total_invested
    return scaled
```

**หมายเหตุ:** target_vol = 0.10 เป็น starting point — ต้อง calibrate ผ่าน Walk-Forward Analysis

---

### 3.6 Rebalance Band (Priority: MEDIUM)

```python
def needs_rebalance(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    band: float = 0.02,    # 2% drift threshold
) -> bool:
    """
    Trade เฉพาะเมื่อ drift เกิน band
    ลด turnover + transaction cost โดยแทบไม่กระทบ signal quality
    """
    all_assets = set(current_weights) | set(target_weights)
    return any(
        abs(current_weights.get(a, 0) - target_weights.get(a, 0)) > band
        for a in all_assets
    )

def compute_trades(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    portfolio_value: float,
) -> list[dict]:
    """
    คำนวณ trades เฉพาะ assets ที่ drift เกิน band
    Return: list of {asset, action, shares, value}
    """
    trades = []
    all_assets = set(current_weights) | set(target_weights)
    
    for asset in all_assets:
        curr = current_weights.get(asset, 0)
        tgt = target_weights.get(asset, 0)
        drift = tgt - curr
        
        if abs(drift) > 0.001:   # minimum trade size (0.1%)
            trades.append({
                "asset": asset,
                "action": "BUY" if drift > 0 else "SELL",
                "weight_change": drift,
                "value_change": drift * portfolio_value,
            })
    
    return trades
```

---

## 4. Pipeline Flow (V3)

```
รายสัปดาห์ (GitHub Actions, Monday 8:00 AM BKK time)
                                    
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Fetch & Score                                      │
│  FRED API → 11 macro indicators                            │
│  → Percentile Rank (Rolling Window 260W)                   │
│  → growth_score (0–100), inflation_score (0–100)           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 2: Regime Probabilities  [NEW V3]                     │
│  Euclidean Distance → 4 centroids                          │
│  → Softmax Function (tau=20)                               │
│  → {Goldilocks: p1, Reflation: p2, Stagflation: p3,        │
│     Deflation: p4}  (ผลรวม = 1.0)                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 3: Blended Allocation  [NEW V3]                       │
│  w = Σ pₖ × Wₖ (Weighted Average)                         │
│  → raw_weights per asset                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 4: Momentum Filter  [NEW V3]                          │
│  yfinance → price history (26W)                            │
│  Dual confirmation: 13W AND 26W < -5%                      │
│  → cut weight 50%, freed → Cash                            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 5: Vol Targeting  [NEW V3]                            │
│  Covariance Matrix (26W) → portfolio σ                     │
│  scale = min(1.0, target_vol / port_vol)                   │
│  → final_weights                                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 6: Rebalance Decision  [NEW V3]                       │
│  drift = |current - target| per asset                      │
│  if max(drift) > 2% → rebalance                           │
│  → trades list                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  Step 7: Output (คงเดิม V2B)                                │
│  → Supabase: store weights, trades, regime_probs           │
│  → Streamlit: update dashboard                             │
│  → Telegram: send weekly summary alert                     │
│  → OpenRouter: generate AI thesis                          │
│  → ML shadow mode: XGBoost prediction (อย่าแตะ)           │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Implementation Priority Order

```
Phase 1 (ทำก่อน, backtest ก่อน deploy):
  [ ] 3.1 แก้ REGIME_WEIGHTS constants
  [ ] 3.2 compute_regime_probabilities()
  [ ] 3.3 compute_blended_weights()
  [ ] backtest V3.1–3.3 vs V2B baseline → OOS Sharpe ต้องดีขึ้น

Phase 2 (ถ้า Phase 1 ผ่าน):
  [ ] 3.4 apply_momentum_filter() (dual 13W/26W)
  [ ] 3.5 apply_vol_targeting() (target 10%)
  [ ] 3.6 needs_rebalance() + compute_trades()
  [ ] backtest V3 full → OOS Sharpe target ≥0.9, MaxDD ≤12%

Phase 3 (integration):
  [ ] update Streamlit dashboard: แสดง regime_probs (4 bars)
  [ ] update Supabase schema: เพิ่ม columns regime_probs, blend_weights
  [ ] update Telegram alert: แสดง top 2 regime probabilities
  [ ] update tests: เพิ่มให้ครอบคลุม V3 functions ทุกตัว
```

---

## 6. Testing Requirements

ทุก function ใหม่ต้องมี tests ก่อน merge:

```python
# ตัวอย่าง test cases ที่ต้องครอบคลุม

def test_regime_probabilities_sum_to_one():
    probs = compute_regime_probabilities(60, 40)
    assert abs(sum(probs.values()) - 1.0) < 1e-9

def test_regime_probabilities_goldilocks_dominates():
    probs = compute_regime_probabilities(80, 20)
    assert probs["GOLDILOCKS"] > 0.5

def test_regime_probabilities_blend_at_center():
    probs = compute_regime_probabilities(50, 50)
    # ที่ center ทุก regime ควรใกล้เคียงกัน (high entropy)
    assert max(probs.values()) < 0.40

def test_blended_weights_investable_sum():
    # investable weights (ไม่รวม Cash) ต้องรวมกันได้ ≈ 80%
    ...

def test_vol_targeting_no_leverage():
    # scale factor ต้องไม่เกิน 1.0 ในทุกกรณี
    ...

def test_rebalance_band_no_trade_when_small_drift():
    current = {"SPY": 0.20, "Cash": 0.80}
    target  = {"SPY": 0.21, "Cash": 0.79}   # drift = 1% < 2% band
    assert not needs_rebalance(current, target)
```

---

## 7. Key Constraints & Rules

```
1. อย่าแตะ ML shadow mode และ XGBoost training pipeline
2. อย่าแตะ FRED API data fetching logic (ถ้า work อยู่)
3. อย่าแตะ Supabase schema columns ที่มีอยู่ (เพิ่มได้ อย่าลบ)
4. Transaction cost: 0.1% proportional (ไม่ใช่ fixed $1)
5. ทุก function ต้อง log ด้วย structlog พร้อม run_id
6. Cash buffer 20% คงที่เสมอ ทุก regime ทุก scenario
7. ไม่ใช้ leverage (scale factor ≤ 1.0)
8. Walk-Forward Analysis ก่อน deploy ทุก phase
9. Telegram alerts ต้องส่งสำเร็จ — ถ้า fail ให้ raise exception ไม่ใช่ silent fail
10. ทุก Supabase write ต้องมี error handling + retry logic
```

---

## 8. Files ที่ต้องแก้ / สร้างใหม่ (ประมาณการ)

```
แก้:
  allocation_engine.py     → REGIME_WEIGHTS constants + blended logic
  regime_classifier.py     → แทน hard switch ด้วย softmax probabilities
  pipeline.py              → เพิ่ม Step 4–6 ใน weekly run

สร้างใหม่:
  momentum_filter.py       → dual 13W/26W filter
  vol_targeting.py         → covariance-based vol targeting
  rebalance.py             → band check + trade computation

tests/:
  test_regime_probabilities.py
  test_blended_allocation.py
  test_momentum_filter.py
  test_vol_targeting.py
  test_rebalance.py

backtest/:
  backtest_v3.py           → Walk-Forward Analysis เปรียบเทียบ V2B vs V3
```

---

## 9. Backtest Acceptance Criteria

V3 ผ่านเมื่อ Walk-Forward Analysis แสดง:

| Metric | V2B Baseline | V3 Target |
|--------|-------------|-----------|
| OOS Sharpe Ratio | 0.80 | ≥ 0.90 |
| Max Drawdown | 16.8% | ≤ 14% |
| Annual Turnover | (วัดใหม่) | ลดลง ≥20% vs V2B |
| NBER Recession Catch | 5/6 | ≥ 5/6 |

ถ้า V3 ไม่ผ่าน criteria → rollback ทั้ง phase กลับไป V2B ก่อน investigate

---

*Document นี้ครอบคลุม context ทั้งหมดของ FlowMacro จากประวัติการออกแบบ V1→V2B
และ V3 design decisions จาก session นี้ เพื่อให้ Claude Code implement ได้โดยไม่ต้องถามบริบทเพิ่ม*
