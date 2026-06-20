"""
Backtest: ML-blend (30/70 XGBoost/rule-based) vs V3 rule-based  — 2020–2026 OOS

Pipeline:
  1. Download FRED + COT + price data from 2010
  2. Compute weekly normalized features (5Y rolling percentile rank)
  3. V3: softmax probabilities → blended weights
  4. ML-blend: XGBoost prediction → 30% ML + 70% rule-based probs → weights
  5. Compute weekly returns (no momentum filter, no vol targeting — apples-to-apples)
  6. Output scripts/backtest_ml_blend.csv

Caveats:
  - XGBoost model trained on NBER 2000–2024 → partial in-sample overlap
  - Slow-release FRED series (IPMAN, UNRATE, GDP) are forward-filled; same lag
    assumption as the live weekly job
  - COT data from 2010 → 5Y rolling window warm-up 2010–2015 → OOS from 2020

Usage: python scripts/backtest_ml_blend.py
"""
from __future__ import annotations

import os
import sys

# allow imports from repo root
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger

from flowmacro.data.sources.fred import fetch_series
from flowmacro.data.sources.cot import fetch_cot_net
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.probabilities import compute_regime_probabilities, compute_ml_blended_probs
from flowmacro.portfolio.allocator import compute_blended_weights
from flowmacro.regime.ml_predictor import predict_ml

_FETCH_START = "2010-01-01"   # warm-up; 5Y rolling window ready by 2015
_OOS_START   = "2020-01-01"   # measure OOS performance from here
_INITIAL     = 10_000.0

_FRED_IDS = ["T10Y2Y", "BAA10Y", "ICSA", "IPMAN", "UNRATE", "A191RL1Q225SBEA", "T5YIE", "CPIAUCSL"]
_COT_IDS  = ["cot_sp500_net", "cot_treasury10y_net", "cot_gold_net", "cot_crude_net"]
_ASSETS   = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "SHY", "GLD", "SLV", "DBC", "UUP", "BTC-USD"]

_OUT_PATH = os.path.join(os.path.dirname(__file__), "backtest_ml_blend.csv")


# ── helpers ──────────────────────────────────────────────────────────────────

def _price_at(series: pd.Series, dt: pd.Timestamp) -> float | None:
    """Most recent price on or before dt."""
    try:
        val = series.asof(dt)
        return float(val) if pd.notna(val) else None
    except Exception:
        return None


def _sharpe(returns: pd.Series) -> float:
    std = returns.std()
    if std == 0:
        return float("nan")
    return float(returns.mean() / std * (52 ** 0.5))


def _maxdd(values: pd.Series) -> float:
    peak = values.cummax()
    dd = (values / peak - 1)
    return float(dd.min() * 100)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── 1. FRED ───────────────────────────────────────────────────────────────
    logger.info("Downloading FRED series...")
    fred: dict[str, pd.Series] = {}
    for sid in _FRED_IDS:
        try:
            fred[sid] = fetch_series(sid, start=_FETCH_START)
            logger.info(f"  {sid}: {len(fred[sid])} rows, last={fred[sid].index[-1].date()}")
        except Exception as exc:
            logger.warning(f"  {sid} FAILED: {exc}")

    # ── 2. COT ────────────────────────────────────────────────────────────────
    logger.info("Downloading COT series (CFTC archives — slow)...")
    cot: dict[str, pd.Series] = {}
    for sid in _COT_IDS:
        try:
            cot[sid] = fetch_cot_net(sid, start=_FETCH_START)
            logger.info(f"  {sid}: {len(cot[sid])} rows")
        except Exception as exc:
            logger.warning(f"  {sid} FAILED: {exc}")

    # ── 3. Prices ─────────────────────────────────────────────────────────────
    logger.info("Downloading price data (yfinance)...")
    price_tickers = list(set(["SPY", "HG=F", "GC=F", "UUP"] + _ASSETS))
    prices: dict[str, pd.Series] = {}
    for tk in price_tickers:
        try:
            df = yf.download(tk, start=_FETCH_START, progress=False, auto_adjust=True)
            if not df.empty:
                prices[tk] = df["Close"].squeeze().dropna()
                logger.info(f"  {tk}: {len(prices[tk])} rows")
        except Exception as exc:
            logger.warning(f"  {tk} FAILED: {exc}")

    # ── 4. Derived series ─────────────────────────────────────────────────────
    copper_gold = pd.Series(dtype=float)
    if "HG=F" in prices and "GC=F" in prices:
        copper_gold = (prices["HG=F"] / prices["GC=F"]).rename("copper_gold")

    spy_200ma = pd.Series(dtype=float)
    if "SPY" in prices:
        spy = prices["SPY"]
        spy_200ma = (spy / spy.rolling(200).mean() - 1).rename("spy_200ma")

    dxy_trend = pd.Series(dtype=float)
    if "UUP" in prices:
        uup = prices["UUP"]
        dxy_trend = (uup / uup.rolling(20).mean() - 1).rename("dxy_trend")

    cpi_yoy = pd.Series(dtype=float)
    if "CPIAUCSL" in fred:
        cpi_yoy = (fred["CPIAUCSL"].pct_change(12) * 100).rename("cpi_yoy")

    # Map indicator.series_id → raw pd.Series
    raw_map: dict[str, pd.Series | None] = {
        "T10Y2Y":           fred.get("T10Y2Y"),
        "BAA10Y":           fred.get("BAA10Y"),
        "ICSA":             fred.get("ICSA"),
        "IPMAN":            fred.get("IPMAN"),
        "UNRATE":           fred.get("UNRATE"),
        "A191RL1Q225SBEA":  fred.get("A191RL1Q225SBEA"),
        "T5YIE":            fred.get("T5YIE"),
        "cpi_yoy":          cpi_yoy if not cpi_yoy.empty else None,
        "copper_gold":      copper_gold if not copper_gold.empty else None,
        "spy_200ma":        spy_200ma if not spy_200ma.empty else None,
        "dxy_trend":        dxy_trend if not dxy_trend.empty else None,
        "cot_sp500_net":        cot.get("cot_sp500_net"),
        "cot_treasury10y_net":  cot.get("cot_treasury10y_net"),
        "cot_gold_net":         cot.get("cot_gold_net"),
        "cot_crude_net":        cot.get("cot_crude_net"),
    }

    # ── 5. Normalize features to weekly Friday ────────────────────────────────
    logger.info("Normalizing features (5Y rolling percentile rank)...")
    norm_weekly_frames: list[pd.Series] = []
    for ind in INDICATORS:
        raw = raw_map.get(ind.series_id)
        if raw is None or raw.empty:
            logger.warning(f"  {ind.name}: no data — will be NaN")
            continue
        daily = raw.resample("D").ffill()
        normed = normalize(daily, ind, window_years=5)
        weekly = normed.resample("W-FRI").last().rename(ind.name)
        norm_weekly_frames.append(weekly)
        logger.info(f"  {ind.name}: OK ({weekly.notna().sum()} non-NaN weekly rows)")

    if not norm_weekly_frames:
        raise RuntimeError("No features computed — aborting")

    norm_w = pd.concat(norm_weekly_frames, axis=1)

    # Compute axis scores and attach
    axis_scores = compute_scores(norm_w)
    norm_w = pd.concat([norm_w, axis_scores], axis=1)

    # Trim to OOS period start
    norm_w = norm_w.loc[_OOS_START:]
    logger.info(f"Weekly feature rows for OOS period: {len(norm_w)}")

    # ── 6. Weekly portfolio asset prices (aligned to Friday) ──────────────────
    asset_prices_wk: dict[str, pd.Series] = {}
    for asset in _ASSETS:
        s = prices.get(asset)
        if s is not None and not s.empty:
            # keep daily (use .asof() for lookup)
            asset_prices_wk[asset] = s

    # ── 7. Walk-forward simulation ────────────────────────────────────────────
    logger.info("Running week-by-week simulation...")

    rb_val = _INITIAL
    ml_val = _INITIAL

    out_rows: list[dict] = []
    dates = norm_w.index.tolist()

    for i, dt in enumerate(dates[:-1]):
        next_dt = dates[i + 1]

        row = norm_w.loc[dt]

        gs  = row.get("growth_score",    float("nan"))
        inf = row.get("inflation_score", float("nan"))

        if pd.isna(gs) or pd.isna(inf):
            continue

        # V3 rule-based probs → blended weights
        rb_probs   = compute_regime_probabilities(float(gs), float(inf))
        rb_weights = compute_blended_weights(rb_probs)

        # ML prediction → blended probs → weights
        feature_scores = {}
        for ind in INDICATORS:
            v = row.get(ind.name, float("nan"))
            feature_scores[ind.name] = 50.0 if pd.isna(v) else float(v)  # fill NaN with neutral

        try:
            ml_regime, ml_conf = predict_ml(feature_scores)
            blend_result = compute_ml_blended_probs(rb_probs, ml_regime, ml_conf, ml_weight=0.30)
            ml_weights   = compute_blended_weights(blend_result.blended)
        except Exception as exc:
            logger.warning(f"  ML failed at {dt.date()}: {exc} — using rule weights")
            ml_regime, ml_conf = max(rb_probs, key=rb_probs.get), 0.0
            ml_weights = rb_weights

        # Compute weekly return for each portfolio
        rb_ret = 0.0
        ml_ret = 0.0

        for asset in set(list(rb_weights.keys()) + list(ml_weights.keys())):
            s = asset_prices_wk.get(asset)
            if s is None:
                continue
            p_cur  = _price_at(s, dt)
            p_next = _price_at(s, next_dt)
            if p_cur is None or p_next is None or p_cur <= 0:
                continue
            asset_ret = (p_next / p_cur) - 1
            rb_ret += rb_weights.get(asset, 0.0) * asset_ret
            ml_ret += ml_weights.get(asset, 0.0) * asset_ret

        rb_val *= (1 + rb_ret)
        ml_val *= (1 + ml_ret)

        rb_regime_label = max(rb_probs, key=rb_probs.get)

        out_rows.append({
            "date":             next_dt.strftime("%Y-%m-%d"),
            "rb_value":         round(rb_val, 4),
            "ml_blend_value":   round(ml_val, 4),
            "rb_return_pct":    round(rb_ret * 100, 4),
            "ml_blend_ret_pct": round(ml_ret * 100, 4),
            "rb_regime":        rb_regime_label,
            "ml_regime":        ml_regime,
            "ml_conf":          round(ml_conf, 2),
            "growth_score":     round(float(gs),  2),
            "inflation_score":  round(float(inf), 2),
        })

    if not out_rows:
        raise RuntimeError("No output rows — check data availability")

    # ── 8. Compute cumulative returns & metrics ───────────────────────────────
    df = pd.DataFrame(out_rows)
    df["rb_cum_pct"]    = (df["rb_value"]       / _INITIAL - 1) * 100
    df["ml_cum_pct"]    = (df["ml_blend_value"]  / _INITIAL - 1) * 100

    # Save
    df.to_csv(_OUT_PATH, index=False)
    logger.info(f"Saved → {_OUT_PATH}  ({len(df)} weeks)")

    # ── 9. Summary ────────────────────────────────────────────────────────────
    rb_sharpe = _sharpe(df["rb_return_pct"])
    ml_sharpe = _sharpe(df["ml_blend_ret_pct"])
    rb_mdd    = _maxdd(df["rb_value"])
    ml_mdd    = _maxdd(df["ml_blend_value"])
    rb_total  = df["rb_cum_pct"].iloc[-1]
    ml_total  = df["ml_cum_pct"].iloc[-1]

    n_agree   = (df["rb_regime"] == df["ml_regime"]).sum()
    agree_pct = n_agree / len(df) * 100

    print(f"\n{'='*55}")
    print(f"ML-blend Backtest  {_OOS_START} -> {df['date'].iloc[-1]}")
    print(f"{'='*55}")
    print(f"{'Metric':<20} {'Rule-based V3':>16} {'ML-blend 30/70':>16}")
    print(f"{'-'*55}")
    print(f"{'Sharpe':<20} {rb_sharpe:>16.3f} {ml_sharpe:>16.3f}")
    print(f"{'Max Drawdown':<20} {rb_mdd:>15.1f}% {ml_mdd:>15.1f}%")
    print(f"{'Total Return':<20} {rb_total:>15.1f}% {ml_total:>15.1f}%")
    print(f"{'='*55}")
    print(f"Regime agreement:  {n_agree}/{len(df)} weeks ({agree_pct:.1f}%)")
    print(f"Output: {_OUT_PATH}")


if __name__ == "__main__":
    main()
