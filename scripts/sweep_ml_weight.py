"""
ML-weight sweep — find the best blend ratio (rule-based V3 vs XGBoost) over the
existing OOS walk-forward window.

Same data + simulation pipeline as scripts/backtest_ml_blend.py, but instead of
a single hardcoded ml_weight=0.30, it runs the *whole sweep in one pass*:
  - FRED/COT/price download: ONCE
  - feature normalization:   ONCE
  - predict_ml() per week:   ONCE (expensive XGBoost call, weight-independent)
  - compute_ml_blended_probs() + portfolio weights + returns: once PER weight
    in `_WEIGHTS`, each tracking its own compounding portfolio value.

Outputs:
  scripts/sweep_ml_weight.csv  — one row per weight: Sharpe, MaxDD, total return
  scripts/sweep_ml_weight.png  — Sharpe & MaxDD vs ml_weight

⚠ Caveat (read before trusting the "best" weight):
  This sweep is run over a SINGLE fixed OOS window (2020 → now, ~330 weeks).
  Picking whichever weight maximizes Sharpe *on this same window* is itself a
  form of in-sample selection — the curve can look great here and still not
  hold up going forward (the more weights you try, the more likely one wins
  by luck). Treat the result as "which weight is clearly bad" (e.g. 0.6–0.7
  if confidence is noisy) rather than "the optimal weight to 2 decimals".
  If you want a defensible number, validate the chosen weight on a later
  OOS slice you have NOT looked at yet, or use a rolling/expanding re-pick.

Usage: python scripts/sweep_ml_weight.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from loguru import logger

from flowmacro.data.sources.fred import fetch_series
from flowmacro.data.sources.cot import fetch_cot_net
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.probabilities import compute_regime_probabilities, compute_ml_blended_probs
from flowmacro.portfolio.allocator import compute_blended_weights
from flowmacro.regime.ml_predictor import predict_ml

_FETCH_START = "2010-01-01"
_OOS_START   = "2020-01-01"
_INITIAL     = 10_000.0
_WEIGHTS     = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

_FRED_IDS = ["T10Y2Y", "BAA10Y", "ICSA", "IPMAN", "UNRATE", "A191RL1Q225SBEA", "T5YIE", "CPIAUCSL"]
_COT_IDS  = ["cot_sp500_net", "cot_treasury10y_net", "cot_gold_net", "cot_crude_net"]
_ASSETS   = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "SHY", "GLD", "SLV", "DBC", "UUP", "BTC-USD"]

_CSV_PATH = os.path.join(os.path.dirname(__file__), "sweep_ml_weight.csv")
_PNG_PATH = os.path.join(os.path.dirname(__file__), "sweep_ml_weight.png")


# ── helpers ──────────────────────────────────────────────────────────────────

def _price_at(series: pd.Series, dt: pd.Timestamp) -> float | None:
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
    axis_scores = compute_scores(norm_w)
    norm_w = pd.concat([norm_w, axis_scores], axis=1)
    norm_w = norm_w.loc[_OOS_START:]
    logger.info(f"Weekly feature rows for OOS period: {len(norm_w)}")

    # ── 6. Weekly portfolio asset prices ──────────────────────────────────────
    asset_prices_wk: dict[str, pd.Series] = {
        asset: prices[asset] for asset in _ASSETS if asset in prices and not prices[asset].empty
    }

    # ── 7. Walk-forward simulation — predict ML once, blend per weight ───────
    logger.info(f"Running week-by-week simulation for {len(_WEIGHTS)} weights: {_WEIGHTS}")

    vals = {w: _INITIAL for w in _WEIGHTS}
    weekly_rows: dict[float, list[dict]] = {w: [] for w in _WEIGHTS}

    dates = norm_w.index.tolist()
    n_agree = 0
    n_total = 0

    for i, dt in enumerate(dates[:-1]):
        next_dt = dates[i + 1]
        row = norm_w.loc[dt]

        gs  = row.get("growth_score",    float("nan"))
        inf = row.get("inflation_score", float("nan"))
        if pd.isna(gs) or pd.isna(inf):
            continue

        rb_probs = compute_regime_probabilities(float(gs), float(inf))

        feature_scores = {}
        for ind in INDICATORS:
            v = row.get(ind.name, float("nan"))
            feature_scores[ind.name] = 50.0 if pd.isna(v) else float(v)

        try:
            ml_regime, ml_conf = predict_ml(feature_scores)
        except Exception as exc:
            logger.warning(f"  ML failed at {dt.date()}: {exc} — skipping ML for this week")
            ml_regime, ml_conf = max(rb_probs, key=rb_probs.get), 0.0

        rb_regime_label = max(rb_probs, key=rb_probs.get)
        n_total += 1
        if rb_regime_label == ml_regime:
            n_agree += 1

        # pre-fetch this week's asset returns once (shared across all weights)
        asset_ret: dict[str, float] = {}
        for asset, s in asset_prices_wk.items():
            p_cur, p_next = _price_at(s, dt), _price_at(s, next_dt)
            if p_cur is None or p_next is None or p_cur <= 0:
                continue
            asset_ret[asset] = (p_next / p_cur) - 1

        for w in _WEIGHTS:
            try:
                blend_result = compute_ml_blended_probs(rb_probs, ml_regime, ml_conf, ml_weight=w)
                w_weights = compute_blended_weights(blend_result.blended)
            except Exception:
                w_weights = compute_blended_weights(rb_probs)

            ret = sum(w_weights.get(a, 0.0) * r for a, r in asset_ret.items())
            vals[w] *= (1 + ret)

            weekly_rows[w].append({
                "date":      next_dt.strftime("%Y-%m-%d"),
                "value":     round(vals[w], 4),
                "ret_pct":   round(ret * 100, 4),
            })

    if n_total == 0:
        raise RuntimeError("No simulated weeks — check data availability")

    agree_pct = n_agree / n_total * 100
    logger.info(f"Rule/ML regime agreement: {n_agree}/{n_total} weeks ({agree_pct:.1f}%)")

    # ── 8. Per-weight metrics ─────────────────────────────────────────────────
    summary_rows = []
    per_weight_df: dict[float, pd.DataFrame] = {}
    for w in _WEIGHTS:
        df = pd.DataFrame(weekly_rows[w])
        per_weight_df[w] = df
        sharpe = _sharpe(df["ret_pct"])
        mdd    = _maxdd(df["value"])
        total  = (df["value"].iloc[-1] / _INITIAL - 1) * 100
        summary_rows.append({
            "ml_weight":    w,
            "sharpe":       round(sharpe, 3),
            "max_dd_pct":   round(mdd, 2),
            "total_ret_pct": round(total, 2),
            "final_value":  round(df["value"].iloc[-1], 2),
        })

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(_CSV_PATH, index=False)
    logger.info(f"Saved summary -> {_CSV_PATH}")

    # ── 9. Plot Sharpe + MaxDD vs weight ──────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(summary["ml_weight"], summary["sharpe"], marker="o", color="#1f77b4")
    ax1.set_xlabel("ml_weight")
    ax1.set_ylabel("Sharpe")
    ax1.set_title("Sharpe vs ML weight")
    ax1.axhline(summary.loc[summary["ml_weight"] == 0.0, "sharpe"].iloc[0],
                color="gray", linestyle="--", linewidth=1, label="weight=0 (pure rule-based)")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.plot(summary["ml_weight"], summary["max_dd_pct"], marker="o", color="#d62728")
    ax2.set_xlabel("ml_weight")
    ax2.set_ylabel("Max Drawdown (%)")
    ax2.set_title("Max Drawdown vs ML weight")
    ax2.grid(alpha=0.3)

    fig.suptitle(f"ML-weight sweep — OOS {_OOS_START} → {per_weight_df[_WEIGHTS[0]]['date'].iloc[-1]} "
                 f"({n_total} weeks, regime agreement {agree_pct:.0f}%)")
    fig.tight_layout()
    fig.savefig(_PNG_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved plot -> {_PNG_PATH}")

    # ── 10. Print table ───────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"ML-weight Sweep  {_OOS_START} -> {per_weight_df[_WEIGHTS[0]]['date'].iloc[-1]}  ({n_total} weeks)")
    print(f"{'='*70}")
    print(f"{'ml_weight':>10} {'Sharpe':>10} {'MaxDD%':>10} {'TotalRet%':>12} {'FinalVal':>12}")
    print(f"{'-'*70}")
    best_sharpe_row = summary.loc[summary["sharpe"].idxmax()]
    for _, r in summary.iterrows():
        marker = "  <- best Sharpe" if r["ml_weight"] == best_sharpe_row["ml_weight"] else ""
        print(f"{r['ml_weight']:>10.1f} {r['sharpe']:>10.3f} {r['max_dd_pct']:>10.1f} "
              f"{r['total_ret_pct']:>12.1f} {r['final_value']:>12.2f}{marker}")
    print(f"{'='*70}")
    print(f"Regime agreement: {n_agree}/{n_total} weeks ({agree_pct:.1f}%)")
    print(f"Output: {_CSV_PATH}")
    print(f"Plot:   {_PNG_PATH}")
    print(f"\n[!] Reminder: best-Sharpe weight on THIS window may be overfit to it.")
    print(f"  Validate on a later, unseen OOS slice before committing to a weight live.")


if __name__ == "__main__":
    main()
