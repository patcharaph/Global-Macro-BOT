"""
FlowMacro V3 vs V2B — Walk-Forward Backtest

Compares three strategies on the same historical data:
  V2B : Hard regime classification → single-regime weights (baseline)
  V3  : Softmax probabilities → blended allocation (no filters)
  V3F : V3 + Dual Momentum Filter (13W/26W) + Vol Targeting (target=10%)

Walk-Forward windows:
  Train 5Y / Test 2Y / Roll 1Y  (gives 8 windows from 2010→2026)
  Primary IS/OOS split: 2010-2019 / 2020-2026

V3 Acceptance Criteria (PRD §9):
  OOS Sharpe     ≥ 0.90  (V2B baseline: 0.80)
  Max Drawdown   ≤ 14.0% (V2B baseline: 16.8%)
  Annual Turnover: ≥ 20% reduction vs V2B

Usage:
    python scripts/backtest_v3.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import vectorbt as vbt
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series
from flowmacro.portfolio.allocator import (
    REGIME_WEIGHTS, _BLEND_REGIMES,
    get_weights, compute_blended_weights,
)
from flowmacro.regime.probabilities import compute_regime_probabilities
from flowmacro.portfolio.momentum_filter import apply_momentum_filter
from flowmacro.portfolio.vol_targeting import apply_vol_targeting

# ── Config ────────────────────────────────────────────────────────────────────

_WARMUP_START  = "2005-01-01"
_BT_START      = "2010-01-01"
_BT_END        = str(date.today())
_IS_END        = "2019-12-31"
_OOS_START     = "2020-01-01"

_OUT_DIR = Path(__file__).parent

# V3 tickers (USO removed; BTC-USD included from 2013)
_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    "GLD", "SLV", "DBC",
    "TLT", "IEF", "SHY", "UUP",
    "BTC-USD",
]

# Walk-forward parameters (train_years / test_years / roll_years)
_WF_TRAIN = 5
_WF_TEST  = 2
_WF_ROLL  = 1

# V3 acceptance criteria
_OOS_SHARPE_TARGET = 0.90
_MAX_DD_TARGET     = 14.0
_TURNOVER_REDUCE   = 0.20  # at least 20% reduction

_INIT_CASH = 3_000.0
_FEES      = 0.001  # 0.1% per side


# ── Build historical scores ───────────────────────────────────────────────────

def build_scores_weekly() -> pd.DataFrame:
    """Read all indicators from Supabase, compute weekly growth + inflation scores."""
    normalized: dict[str, pd.Series] = {}
    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_WARMUP_START)
            if raw.empty:
                logger.warning(f"  No data: {ind.name} ({ind.series_id})")
                continue
            daily = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
        except Exception as exc:
            logger.warning(f"  Skipped {ind.name}: {exc}")

    if len(normalized) < 5:
        raise ValueError(f"Only {len(normalized)} indicators loaded — need 5+")

    logger.info(f"Indicators loaded: {len(normalized)}")
    normed_df = pd.DataFrame(normalized).loc[_BT_START:]
    scores_df = compute_scores(normed_df)
    weekly    = scores_df.resample("W-FRI").last().dropna(subset=["growth_score", "inflation_score"])
    logger.info(f"Weekly score rows: {len(weekly)}")
    return weekly


# ── Weight builders ───────────────────────────────────────────────────────────

def build_v2b_weights(
    scores_weekly: pd.DataFrame,
    tickers: list[str],
) -> dict[pd.Timestamp, dict[str, float]]:
    """V2B: hard classify → single-regime weights."""
    regimes_df = classify_series(scores_weekly)
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for dt, row in regimes_df.iterrows():
        regime = row["regime"]
        result[dt] = get_weights(regime, tickers)
    return result


def build_v3_weights(
    scores_weekly: pd.DataFrame,
    prices_daily: pd.DataFrame,
    tickers: list[str],
    with_filters: bool = False,
) -> dict[pd.Timestamp, dict[str, float]]:
    """V3: softmax probabilities → blended allocation.
    If with_filters: also applies dual momentum filter and vol targeting.
    """
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for dt, row in scores_weekly.iterrows():
        g = float(row["growth_score"])
        i = float(row["inflation_score"])
        if np.isnan(g) or np.isnan(i):
            continue

        probs   = compute_regime_probabilities(g, i)
        blended = compute_blended_weights(probs)

        if with_filters and not prices_daily.empty:
            lookback_start = dt - pd.Timedelta(weeks=32)
            ph = prices_daily.loc[lookback_start:dt].resample("W").last().dropna(how="all")
            blend_assets = [a for a in blended if a != "Cash" and a in ph.columns]
            if len(blend_assets) >= 2:
                ph_f = ph[blend_assets]
                try:
                    blended = apply_momentum_filter(blended, ph_f)
                    returns_df = ph_f.pct_change().dropna()
                    blended = apply_vol_targeting(blended, returns_df)
                except Exception as exc:
                    logger.debug(f"Filter skipped at {dt.date()}: {exc}")

        result[dt] = blended
    return result


# ── Convert weights dict to daily DataFrame ───────────────────────────────────

def to_daily_weights(
    weights_dict: dict[pd.Timestamp, dict[str, float]],
    tickers: list[str],
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Sparse daily weight DataFrame — NaN on non-rebalance days (hold position)."""
    df = pd.DataFrame(np.nan, index=price_index, columns=tickers)
    for dt, w in weights_dict.items():
        rebal_dates = price_index[price_index >= dt]
        if len(rebal_dates) == 0:
            continue
        actual_dt = rebal_dates[0]
        for ticker in tickers:
            df.loc[actual_dt, ticker] = w.get(ticker, 0.0)
    return df


# ── Annual turnover ───────────────────────────────────────────────────────────

def annual_turnover(weights_dict: dict[pd.Timestamp, dict[str, float]]) -> float:
    """Sum of |Δweight| at each rebalance, annualized."""
    dates  = sorted(weights_dict.keys())
    years  = (dates[-1] - dates[0]).days / 365.25 if len(dates) > 1 else 1.0
    total  = 0.0
    assets = set()
    for w in weights_dict.values():
        assets.update(w.keys())

    prev: dict[str, float] = {}
    for dt in dates:
        curr = weights_dict[dt]
        if prev:
            total += sum(abs(curr.get(a, 0.0) - prev.get(a, 0.0)) for a in assets)
        prev = curr

    return total / years if years > 0 else 0.0


# ── Run vectorbt backtest ─────────────────────────────────────────────────────

def _vbt_run(prices: pd.DataFrame, weights: pd.DataFrame) -> dict:
    try:
        pf = vbt.Portfolio.from_orders(
            close=prices,
            size=weights,
            size_type="targetpercent",
            fees=_FEES,
            fixed_fees=0.0,
            init_cash=_INIT_CASH,
            freq="1D",
            group_by=True,
            cash_sharing=True,
        )
        stats  = pf.stats()
        equity = pf.value()
        return {
            "sharpe_ratio":     round(float(stats["Sharpe Ratio"]), 3),
            "max_drawdown_pct": round(abs(float(stats["Max Drawdown [%]"])), 2),
            "total_return_pct": round(float(stats["Total Return [%]"]), 2),
            "equity_curve":     (equity / equity.iloc[0] * 100),
        }
    except Exception as exc:
        logger.error(f"vectorbt error: {exc}")
        return {"sharpe_ratio": float("nan"), "max_drawdown_pct": float("nan"),
                "total_return_pct": float("nan"), "equity_curve": pd.Series(dtype=float)}


# ── Walk-Forward Analysis ─────────────────────────────────────────────────────

def walk_forward(
    scores_weekly: pd.DataFrame,
    prices_daily: pd.DataFrame,
    tickers: list[str],
) -> dict:
    """Rolling windows: train=5Y / test=2Y / roll=1Y.
    Returns per-window OOS Sharpe for V2B, V3, V3F.
    """
    start_year = int(_BT_START[:4])
    end_year   = int(_BT_END[:4])

    windows = []
    train_start_y = start_year
    while True:
        train_end_y = train_start_y + _WF_TRAIN - 1
        test_end_y  = train_end_y + _WF_TEST
        if test_end_y > end_year:
            break
        windows.append((
            f"{train_start_y}-01-01", f"{train_end_y}-12-31",
            f"{train_end_y + 1}-01-01", f"{test_end_y}-12-31",
        ))
        train_start_y += _WF_ROLL

    logger.info(f"Walk-Forward: {len(windows)} windows (train={_WF_TRAIN}Y / test={_WF_TEST}Y / roll={_WF_ROLL}Y)")

    wf_results: list[dict] = []
    for i, (ts, te, oos_s, oos_e) in enumerate(windows, 1):
        label = f"WF{i}: train {ts[:4]}-{te[:4]} | test {oos_s[:4]}-{oos_e[:4]}"
        logger.info(f"  {label}")
        try:
            oos_scores  = scores_weekly.loc[oos_s:oos_e]
            oos_prices  = prices_daily.loc[oos_s:oos_e]
            avail       = [t for t in tickers if t in oos_prices.columns]
            oos_prices  = oos_prices[avail]

            w_v2b = build_v2b_weights(oos_scores, avail)
            w_v3  = build_v3_weights(oos_scores, oos_prices, avail, with_filters=False)
            w_v3f = build_v3_weights(oos_scores, oos_prices, avail, with_filters=True)

            df_v2b = to_daily_weights(w_v2b, avail, oos_prices.index)
            df_v3  = to_daily_weights(w_v3,  avail, oos_prices.index)
            df_v3f = to_daily_weights(w_v3f, avail, oos_prices.index)

            r_v2b = _vbt_run(oos_prices, df_v2b)
            r_v3  = _vbt_run(oos_prices, df_v3)
            r_v3f = _vbt_run(oos_prices, df_v3f)

            row = {
                "window": label,
                "v2b_sharpe": r_v2b["sharpe_ratio"],
                "v3_sharpe":  r_v3["sharpe_ratio"],
                "v3f_sharpe": r_v3f["sharpe_ratio"],
                "v2b_dd":     r_v2b["max_drawdown_pct"],
                "v3_dd":      r_v3["max_drawdown_pct"],
                "v3f_dd":     r_v3f["max_drawdown_pct"],
            }
            wf_results.append(row)
            logger.info(f"    V2B Sharpe={r_v2b['sharpe_ratio']:.2f} DD={r_v2b['max_drawdown_pct']:.1f}%  |  "
                        f"V3 Sharpe={r_v3['sharpe_ratio']:.2f} DD={r_v3['max_drawdown_pct']:.1f}%  |  "
                        f"V3F Sharpe={r_v3f['sharpe_ratio']:.2f} DD={r_v3f['max_drawdown_pct']:.1f}%")
        except Exception as exc:
            logger.warning(f"  Window {i} failed: {exc}")

    return wf_results


# ── Chart ─────────────────────────────────────────────────────────────────────

def _plot(
    is_v2b: dict, is_v3: dict, is_v3f: dict,
    oos_v2b: dict, oos_v3: dict, oos_v3f: dict,
    wf_results: list[dict],
    out_path: Path,
) -> None:
    fig = plt.figure(figsize=(20, 14))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.40, wspace=0.30)
    ax_is  = fig.add_subplot(gs[0, 0])
    ax_oos = fig.add_subplot(gs[0, 1])
    ax_wf  = fig.add_subplot(gs[1, 0])
    ax_tbl = fig.add_subplot(gs[1, 1])

    fig.suptitle("FlowMacro V3 vs V2B — Walk-Forward Backtest", fontsize=14, fontweight="bold")

    def _draw(ax, results: list[tuple[str, dict, str, str]], title: str):
        for label, r, color, ls in results:
            c = r.get("equity_curve")
            if c is not None and not c.empty:
                ax.plot(c.index, c.values, color=color, lw=2, ls=ls, label=label)
        ax.set_title(title, fontsize=11)
        ax.set_ylabel("Normalised Value (start=100)")
        ax.axhline(100, color="gray", lw=0.6, ls="--")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)

    _draw(ax_is, [
        ("V2B", is_v2b, "#e74c3c", "-"),
        ("V3",  is_v3,  "#2ecc71", "-"),
        ("V3F", is_v3f, "#3498db", "--"),
    ], "In-Sample 2010–2019")

    _draw(ax_oos, [
        ("V2B", oos_v2b, "#e74c3c", "-"),
        ("V3",  oos_v3,  "#2ecc71", "-"),
        ("V3F", oos_v3f, "#3498db", "--"),
    ], "Out-of-Sample 2020–present")

    # Walk-forward Sharpe bar chart
    if wf_results:
        wf_df = pd.DataFrame(wf_results)
        x = np.arange(len(wf_df))
        w = 0.25
        ax_wf.bar(x - w, wf_df["v2b_sharpe"], w, label="V2B", color="#e74c3c", alpha=0.8)
        ax_wf.bar(x,     wf_df["v3_sharpe"],  w, label="V3",  color="#2ecc71", alpha=0.8)
        ax_wf.bar(x + w, wf_df["v3f_sharpe"], w, label="V3F", color="#3498db", alpha=0.8)
        ax_wf.axhline(_OOS_SHARPE_TARGET, color="gold", ls="--", lw=1.5, label=f"Target ≥{_OOS_SHARPE_TARGET}")
        ax_wf.axhline(0, color="gray", lw=0.5)
        ax_wf.set_xticks(x)
        ax_wf.set_xticklabels([r["window"].split("|")[1].strip() for r in wf_results], rotation=30, ha="right", fontsize=7)
        ax_wf.set_title("Walk-Forward OOS Sharpe", fontsize=11)
        ax_wf.legend(fontsize=8)
        ax_wf.grid(alpha=0.2)

    # Metrics table
    ax_tbl.axis("off")
    rows = [
        ["Metric", "IS V2B", "IS V3", "IS V3F", "OOS V2B", "OOS V3", "OOS V3F", "Target"],
        ["Sharpe",
         f"{is_v2b.get('sharpe_ratio', '-'):.2f}",
         f"{is_v3.get('sharpe_ratio', '-'):.2f}",
         f"{is_v3f.get('sharpe_ratio', '-'):.2f}",
         f"{oos_v2b.get('sharpe_ratio', '-'):.2f}",
         f"{oos_v3.get('sharpe_ratio', '-'):.2f}",
         f"{oos_v3f.get('sharpe_ratio', '-'):.2f}",
         f"≥{_OOS_SHARPE_TARGET}"],
        ["Max DD %",
         f"{is_v2b.get('max_drawdown_pct', '-'):.1f}",
         f"{is_v3.get('max_drawdown_pct', '-'):.1f}",
         f"{is_v3f.get('max_drawdown_pct', '-'):.1f}",
         f"{oos_v2b.get('max_drawdown_pct', '-'):.1f}",
         f"{oos_v3.get('max_drawdown_pct', '-'):.1f}",
         f"{oos_v3f.get('max_drawdown_pct', '-'):.1f}",
         f"≤{_MAX_DD_TARGET}"],
        ["Total Ret %",
         f"{is_v2b.get('total_return_pct', '-'):.1f}",
         f"{is_v3.get('total_return_pct', '-'):.1f}",
         f"{is_v3f.get('total_return_pct', '-'):.1f}",
         f"{oos_v2b.get('total_return_pct', '-'):.1f}",
         f"{oos_v3.get('total_return_pct', '-'):.1f}",
         f"{oos_v3f.get('total_return_pct', '-'):.1f}",
         "—"],
    ]
    tbl = ax_tbl.table(cellText=rows[1:], colLabels=rows[0], loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.8)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2c3e50")
            cell.set_text_props(color="white", fontweight="bold")
    ax_tbl.set_title("Metrics Summary", fontsize=11, pad=15)

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    logger.info(f"Chart saved → {out_path}")
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== FlowMacro V3 vs V2B Backtest ===")

    # 1. Build historical scores
    logger.info("Step 1/4 — Building weekly regime scores from Supabase...")
    scores_weekly = build_scores_weekly()

    # 2. Fetch prices
    logger.info("Step 2/4 — Fetching price history...")
    raw = yf.download(_TICKERS, start=_BT_START, auto_adjust=True, progress=False)
    prices_daily: pd.DataFrame = raw["Close"].dropna(how="all")
    avail_all = [t for t in _TICKERS if t in prices_daily.columns]
    prices_daily = prices_daily[avail_all]
    logger.info(f"Prices: {prices_daily.shape[1]} tickers, {len(prices_daily)} days")

    # 3. IS + OOS backtests
    logger.info("Step 3/4 — Running IS/OOS backtests...")

    def _run_period(label: str, start: str, end: str) -> tuple[dict, dict, dict, float, float, float]:
        s_w  = scores_weekly.loc[start:end]
        p_d  = prices_daily.loc[start:end]
        avail = [t for t in avail_all if t in p_d.columns]
        p_d  = p_d[avail]

        w_v2b = build_v2b_weights(s_w, avail)
        w_v3  = build_v3_weights(s_w, p_d, avail, with_filters=False)
        w_v3f = build_v3_weights(s_w, p_d, avail, with_filters=True)

        df_v2b = to_daily_weights(w_v2b, avail, p_d.index)
        df_v3  = to_daily_weights(w_v3,  avail, p_d.index)
        df_v3f = to_daily_weights(w_v3f, avail, p_d.index)

        r_v2b = _vbt_run(p_d, df_v2b)
        r_v3  = _vbt_run(p_d, df_v3)
        r_v3f = _vbt_run(p_d, df_v3f)

        to_v2b = annual_turnover(w_v2b)
        to_v3  = annual_turnover(w_v3)
        to_v3f = annual_turnover(w_v3f)

        logger.info(
            f"{label}: V2B Sharpe={r_v2b['sharpe_ratio']:.2f} DD={r_v2b['max_drawdown_pct']:.1f}% TO={to_v2b:.2f} | "
            f"V3 Sharpe={r_v3['sharpe_ratio']:.2f} DD={r_v3['max_drawdown_pct']:.1f}% TO={to_v3:.2f} | "
            f"V3F Sharpe={r_v3f['sharpe_ratio']:.2f} DD={r_v3f['max_drawdown_pct']:.1f}% TO={to_v3f:.2f}"
        )
        return r_v2b, r_v3, r_v3f, to_v2b, to_v3, to_v3f

    is_v2b,  is_v3,  is_v3f,  to_is_v2b,  to_is_v3,  to_is_v3f  = _run_period("IS",  _BT_START, _IS_END)
    oos_v2b, oos_v3, oos_v3f, to_oos_v2b, to_oos_v3, to_oos_v3f = _run_period("OOS", _OOS_START, _BT_END)

    # 4. Walk-Forward
    logger.info("Step 4/4 — Walk-Forward Analysis...")
    wf_results = walk_forward(scores_weekly, prices_daily, avail_all)

    # ── Acceptance Check ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("V3 ACCEPTANCE CRITERIA (PRD S9)")
    print("=" * 70)

    oos_v3_sharpe = oos_v3["sharpe_ratio"]
    oos_v3f_sharpe = oos_v3f["sharpe_ratio"]
    oos_v3_dd  = oos_v3["max_drawdown_pct"]
    oos_v3f_dd = oos_v3f["max_drawdown_pct"]

    turnover_reduction_v3  = 1 - (to_oos_v3  / to_oos_v2b) if to_oos_v2b > 0 else 0.0
    turnover_reduction_v3f = 1 - (to_oos_v3f / to_oos_v2b) if to_oos_v2b > 0 else 0.0

    wf_v3_sharpes  = [r["v3_sharpe"]  for r in wf_results if not np.isnan(r.get("v3_sharpe", float("nan")))]
    wf_v3f_sharpes = [r["v3f_sharpe"] for r in wf_results if not np.isnan(r.get("v3f_sharpe", float("nan")))]
    wf_v3_mean  = np.mean(wf_v3_sharpes)  if wf_v3_sharpes  else float("nan")
    wf_v3f_mean = np.mean(wf_v3f_sharpes) if wf_v3f_sharpes else float("nan")

    def _chk(ok, desc, actual, target, unit=""):
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {desc:40s}  actual={actual:.3f}{unit}  target={target}{unit}")
        return ok

    checks = []
    checks.append(_chk(oos_v3_sharpe   >= _OOS_SHARPE_TARGET,
                       "V3  OOS Sharpe",    oos_v3_sharpe,   _OOS_SHARPE_TARGET))
    checks.append(_chk(oos_v3f_sharpe  >= _OOS_SHARPE_TARGET,
                       "V3F OOS Sharpe",    oos_v3f_sharpe,  _OOS_SHARPE_TARGET))
    checks.append(_chk(oos_v3_dd       <= _MAX_DD_TARGET,
                       "V3  OOS Max DD",    oos_v3_dd,       _MAX_DD_TARGET,    "%"))
    checks.append(_chk(oos_v3f_dd      <= _MAX_DD_TARGET,
                       "V3F OOS Max DD",    oos_v3f_dd,      _MAX_DD_TARGET,    "%"))
    checks.append(_chk(turnover_reduction_v3  >= _TURNOVER_REDUCE,
                       "V3  Turnover reduction",  turnover_reduction_v3,  _TURNOVER_REDUCE))
    checks.append(_chk(turnover_reduction_v3f >= _TURNOVER_REDUCE,
                       "V3F Turnover reduction",  turnover_reduction_v3f, _TURNOVER_REDUCE))
    if not np.isnan(wf_v3_mean):
        checks.append(_chk(wf_v3_mean  >= _OOS_SHARPE_TARGET,
                           f"V3  WF mean OOS Sharpe ({len(wf_v3_sharpes)} windows)",  wf_v3_mean,  _OOS_SHARPE_TARGET))
    if not np.isnan(wf_v3f_mean):
        checks.append(_chk(wf_v3f_mean >= _OOS_SHARPE_TARGET,
                           f"V3F WF mean OOS Sharpe ({len(wf_v3f_sharpes)} windows)", wf_v3f_mean, _OOS_SHARPE_TARGET))

    passed = sum(checks)
    total  = len(checks)
    print(f"\n  Score: {passed}/{total}")
    if passed == total:
        verdict = "ALL PASS — V3 ready for deployment"
    elif passed >= total * 0.75:
        verdict = "MARGINAL — review failed criteria before deploy"
    else:
        verdict = "FAIL — V3 does not meet criteria; rollback or investigate"
    print(f"  {verdict}")
    print("=" * 70)

    # ── Detailed report ───────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("DETAILED RESULTS")
    print("-" * 70)
    print(f"  {'Strategy':<8} {'Period':<12} {'Sharpe':>7} {'MaxDD%':>8} {'TotalRet%':>11} {'Ann.TO':>8}")
    print("  " + "-" * 54)
    for strat, lbl, r, to in [
        ("V2B",  "IS  2010-19", is_v2b,  to_is_v2b),
        ("V3",   "IS  2010-19", is_v3,   to_is_v3),
        ("V3F",  "IS  2010-19", is_v3f,  to_is_v3f),
        ("V2B",  "OOS 2020-now", oos_v2b, to_oos_v2b),
        ("V3",   "OOS 2020-now", oos_v3,  to_oos_v3),
        ("V3F",  "OOS 2020-now", oos_v3f, to_oos_v3f),
    ]:
        print(f"  {strat:<8} {lbl:<12} {r['sharpe_ratio']:>7.2f} {r['max_drawdown_pct']:>8.1f} "
              f"{r['total_return_pct']:>11.1f} {to:>8.2f}")

    if wf_results:
        print("\n  Walk-Forward OOS Sharpe (per window):")
        print(f"  {'Window':<40} {'V2B':>6} {'V3':>6} {'V3F':>6}")
        for r in wf_results:
            print(f"  {r['window']:<40} {r['v2b_sharpe']:>6.2f} {r['v3_sharpe']:>6.2f} {r['v3f_sharpe']:>6.2f}")
        print(f"\n  WF Mean OOS Sharpe — V2B: {np.mean([r['v2b_sharpe'] for r in wf_results]):.2f} | "
              f"V3: {wf_v3_mean:.2f} | V3F: {wf_v3f_mean:.2f}")

    # ── Save outputs ──────────────────────────────────────────────────────────
    curves = {}
    for name, r in [("is_v2b", is_v2b), ("is_v3", is_v3), ("is_v3f", is_v3f),
                    ("oos_v2b", oos_v2b), ("oos_v3", oos_v3), ("oos_v3f", oos_v3f)]:
        c = r.get("equity_curve")
        if c is not None and not c.empty:
            curves[name] = c

    out_csv = _OUT_DIR / "backtest_v3.csv"
    pd.DataFrame(curves).to_csv(out_csv)
    logger.info(f"CSV → {out_csv}")

    if wf_results:
        wf_csv = _OUT_DIR / "backtest_v3_walkforward.csv"
        pd.DataFrame(wf_results).to_csv(wf_csv, index=False)
        logger.info(f"WF CSV → {wf_csv}")

    out_png = _OUT_DIR / "backtest_v3.png"
    _plot(is_v2b, is_v3, is_v3f, oos_v2b, oos_v3, oos_v3f, wf_results, out_png)

    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
