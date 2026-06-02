#!/usr/bin/env python3
"""
Branch B — Strategy performance validation.

Pass criteria (both periods must pass):
  - Sharpe Ratio  >= 0.7
  - Max Drawdown  <= 25%
  - Sharpe > SPY buy-and-hold (risk-adjusted outperformance)

Train/test split:
  - In-sample:    2010-01-01 → 2019-12-31
  - Out-of-sample: 2020-01-01 → present  (COVID + inflation + rate hike cycles)

Output:
  scripts/validate_strategy.csv  — daily equity curves for both periods
  scripts/validate_strategy.png  — 3-panel chart: IS, OOS, metrics table
"""

from pathlib import Path
from datetime import date
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series
from flowmacro.backtest.engine import run_backtest

_WARMUP_START = "2005-01-01"
_IS_START     = "2010-01-01"
_IS_END       = "2019-12-31"
_OOS_START    = "2020-01-01"
_OOS_END      = str(date.today())
_OUT_DIR      = Path(__file__).parent

_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    "GLD", "SLV", "DBC", "USO",
    "TLT", "IEF", "UUP", "BTC-USD",
]

# Pass criteria
_MIN_SHARPE   = 0.7
_MAX_DD       = 25.0


# ── Regime series ─────────────────────────────────────────────────────────────

def build_regime_series(start: str, end: str) -> pd.Series:
    """Read Supabase indicators, compute percentile ranks, classify weekly."""
    normalized: dict[str, pd.Series] = {}
    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_WARMUP_START)
            if raw.empty:
                logger.warning(f"  No data: {ind.name}")
                continue
            daily = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
        except Exception as exc:
            logger.warning(f"  Skipped {ind.name}: {exc}")

    if len(normalized) < 5:
        raise ValueError(f"Only {len(normalized)} indicators — need 5+")

    normed_df = pd.DataFrame(normalized).loc[start:end]
    scores    = compute_scores(normed_df)
    regimes   = classify_series(scores)
    weekly    = regimes["regime"].resample("W-FRI").last().dropna()

    dist = weekly.value_counts().to_dict()
    logger.info(f"  Regime distribution ({start[:4]}-{end[:4]}): {dist}")
    return weekly


# ── Prices ────────────────────────────────────────────────────────────────────

def fetch_prices(start: str, end: str) -> pd.DataFrame:
    logger.info(f"  Downloading prices {start} → {end}...")
    raw = yf.download(_TICKERS, start=start, end=end,
                      auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")
    logger.info(f"  {prices.shape[1]} tickers, {len(prices)} days")
    return prices


# ── SPY benchmark ─────────────────────────────────────────────────────────────

def _spy_metrics(prices: pd.DataFrame) -> dict:
    """Compute Sharpe + Max DD for SPY buy-and-hold."""
    spy = prices["SPY"].dropna()
    ret = spy.pct_change().dropna()
    sharpe = (ret.mean() / ret.std()) * np.sqrt(252)
    roll_max = spy.cummax()
    dd = ((spy - roll_max) / roll_max).min() * 100
    total_ret = (spy.iloc[-1] / spy.iloc[0] - 1) * 100
    return {
        "sharpe_ratio":     round(float(sharpe), 3),
        "max_drawdown_pct": round(abs(float(dd)), 2),
        "total_return_pct": round(float(total_ret), 2),
    }


# ── Pass/fail ─────────────────────────────────────────────────────────────────

def _verdict(strat: dict, spy: dict, label: str) -> list[str]:
    lines = [f"\n--- {label} ---"]
    checks = [
        ("Sharpe >= 0.7",       strat["sharpe_ratio"]    >= _MIN_SHARPE,
         f"{strat['sharpe_ratio']:.2f}  (SPY: {spy['sharpe_ratio']:.2f})"),
        ("Max DD <= 25%",       strat["max_drawdown_pct"] <= _MAX_DD,
         f"{strat['max_drawdown_pct']:.1f}%  (SPY: {spy['max_drawdown_pct']:.1f}%)"),
        ("Sharpe > SPY",        strat["sharpe_ratio"]    >  spy["sharpe_ratio"],
         f"{strat['sharpe_ratio']:.2f} vs {spy['sharpe_ratio']:.2f}"),
    ]
    passed = 0
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        lines.append(f"  [{status}] {name:25s}  {detail}")
        if ok:
            passed += 1
    lines.append(f"  Score: {passed}/{len(checks)}")
    return lines, passed, len(checks)


# ── Chart ─────────────────────────────────────────────────────────────────────

def _plot(is_result: dict, oos_result: dict,
          is_spy: pd.Series, oos_spy: pd.Series,
          is_metrics: tuple, oos_metrics: tuple,
          out_path: Path) -> None:

    fig = plt.figure(figsize=(18, 11))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3)

    ax_is  = fig.add_subplot(gs[0, 0])
    ax_oos = fig.add_subplot(gs[0, 1])
    ax_tbl = fig.add_subplot(gs[1, :])
    ax_tbl.axis("off")

    fig.suptitle("FlowMacro — Strategy Validation (Branch B)", fontsize=14, fontweight="bold")

    def _draw_curves(ax, result, spy_series, title):
        strat_curve = result.get("equity_curve")
        bench_curve = result.get("equity_curve_benchmark")
        spy_norm    = (spy_series / spy_series.iloc[0] * 100).dropna()

        if strat_curve is not None and not strat_curve.empty:
            ax.plot(strat_curve.index, strat_curve.values,
                    color="#2ecc71", lw=2, label="FlowMacro")
        if bench_curve is not None and not bench_curve.empty:
            ax.plot(bench_curve.index, bench_curve.values,
                    color="#3498db", lw=1.5, ls="--", label="60/40")
        if not spy_norm.empty:
            ax.plot(spy_norm.index, spy_norm.values,
                    color="#e74c3c", lw=1.5, ls=":", label="SPY B&H")

        ax.set_title(title, fontsize=11)
        ax.set_ylabel("Portfolio Value (start=100)")
        ax.axhline(100, color="gray", lw=0.6, ls="--")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)

    _draw_curves(ax_is,  is_result,  is_spy,  "In-Sample 2010-2019")
    _draw_curves(ax_oos, oos_result, oos_spy, "Out-of-Sample 2020-present")

    # Metrics table
    s_is  = is_result["strategy"];       b_is  = is_result["benchmark_60_40"]
    s_oos = oos_result["strategy"];      b_oos = oos_result["benchmark_60_40"]
    is_spy_m,  oos_spy_m  = is_metrics, oos_metrics

    def _p(ok): return "PASS" if ok else "FAIL"

    rows = [
        ["Metric", "IS FlowMacro", "IS 60/40", "IS SPY", "Pass?",
                   "OOS FlowMacro", "OOS 60/40", "OOS SPY", "Pass?"],
        ["Sharpe",
         f"{s_is['sharpe_ratio']:.2f}", f"{b_is['sharpe_ratio']:.2f}", f"{is_spy_m['sharpe_ratio']:.2f}",
         _p(s_is["sharpe_ratio"] >= _MIN_SHARPE and s_is["sharpe_ratio"] > is_spy_m["sharpe_ratio"]),
         f"{s_oos['sharpe_ratio']:.2f}", f"{b_oos['sharpe_ratio']:.2f}", f"{oos_spy_m['sharpe_ratio']:.2f}",
         _p(s_oos["sharpe_ratio"] >= _MIN_SHARPE and s_oos["sharpe_ratio"] > oos_spy_m["sharpe_ratio"])],
        ["Max DD %",
         f"{s_is['max_drawdown_pct']:.1f}", f"{b_is['max_drawdown_pct']:.1f}", f"{is_spy_m['max_drawdown_pct']:.1f}",
         _p(s_is["max_drawdown_pct"] <= _MAX_DD),
         f"{s_oos['max_drawdown_pct']:.1f}", f"{b_oos['max_drawdown_pct']:.1f}", f"{oos_spy_m['max_drawdown_pct']:.1f}",
         _p(s_oos["max_drawdown_pct"] <= _MAX_DD)],
        ["Total Ret %",
         f"{s_is['total_return_pct']:.1f}", f"{b_is['total_return_pct']:.1f}", f"{is_spy_m['total_return_pct']:.1f}",
         "—",
         f"{s_oos['total_return_pct']:.1f}", f"{b_oos['total_return_pct']:.1f}", f"{oos_spy_m['total_return_pct']:.1f}",
         "—"],
    ]

    col_colors = [["#ecf0f1"] * 9] + [["white"] * 9] * (len(rows) - 1)
    tbl = ax_tbl.table(cellText=rows[1:], colLabels=rows[0],
                       loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)

    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2c3e50")
            cell.set_text_props(color="white", fontweight="bold")
        elif c in (4, 8):
            txt = cell.get_text().get_text()
            cell.set_facecolor("#d5f5e3" if txt == "PASS" else "#fadbd8")
    ax_tbl.set_title("Metrics Summary", fontsize=11, pad=15)

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    logger.info(f"Chart saved -> {out_path}")
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== Branch B: Strategy Performance Validation ===")

    # 1. Build regime series
    logger.info("Building in-sample regime series (2010-2019)...")
    is_regimes  = build_regime_series(_IS_START,  _IS_END)

    logger.info("Building out-of-sample regime series (2020-present)...")
    oos_regimes = build_regime_series(_OOS_START, _OOS_END)

    # 2. Fetch prices
    logger.info("Fetching prices...")
    is_prices   = fetch_prices(_IS_START,  _IS_END)
    oos_prices  = fetch_prices(_OOS_START, _OOS_END)

    available_is  = [t for t in _TICKERS if t in is_prices.columns]
    available_oos = [t for t in _TICKERS if t in oos_prices.columns]

    # 3. Run backtests
    logger.info("Running in-sample backtest...")
    is_result   = run_backtest(is_prices[available_is],   is_regimes)

    logger.info("Running out-of-sample backtest...")
    oos_result  = run_backtest(oos_prices[available_oos], oos_regimes)

    # 4. SPY benchmarks
    is_spy_metrics  = _spy_metrics(is_prices)
    oos_spy_metrics = _spy_metrics(oos_prices)

    # 5. Report
    print("\n" + "=" * 60)
    print("STRATEGY VALIDATION REPORT")
    print("=" * 60)

    all_lines = []
    total_passed = total_checks = 0
    for label, result, spy_m in [
        ("IN-SAMPLE  (2010-2019)",   is_result,  is_spy_metrics),
        ("OUT-OF-SAMPLE (2020-now)", oos_result, oos_spy_metrics),
    ]:
        lines, p, c = _verdict(result["strategy"], spy_m, label)
        all_lines.extend(lines)
        total_passed += p
        total_checks += c

    for line in all_lines:
        print(line)

    print("\n" + "=" * 60)
    overall = total_passed == total_checks
    if overall:
        verdict = "VALIDATION PASSED -- proceed to Branch C"
    elif total_passed >= total_checks - 1:
        verdict = "MARGINAL -- review failed criterion before Branch C"
    else:
        verdict = "VALIDATION FAILED -- review strategy design"
    print(f"  Overall {total_passed}/{total_checks} checks   {verdict}")
    print("=" * 60)

    # 6. Save CSV
    out_csv = _OUT_DIR / "validate_strategy.csv"
    curves = {}
    if (c := is_result.get("equity_curve"))  is not None: curves["is_flowmacro"]  = c
    if (c := is_result.get("equity_curve_benchmark")) is not None: curves["is_60_40"] = c
    if (c := oos_result.get("equity_curve")) is not None: curves["oos_flowmacro"] = c
    if (c := oos_result.get("equity_curve_benchmark")) is not None: curves["oos_60_40"] = c
    pd.DataFrame(curves).to_csv(out_csv)
    logger.info(f"CSV -> {out_csv}")

    # 7. Chart
    is_spy_series  = is_prices["SPY"].dropna()  if "SPY" in is_prices.columns  else pd.Series()
    oos_spy_series = oos_prices["SPY"].dropna() if "SPY" in oos_prices.columns else pd.Series()
    out_png = _OUT_DIR / "validate_strategy.png"
    _plot(is_result, oos_result,
          is_spy_series, oos_spy_series,
          is_spy_metrics, oos_spy_metrics,
          out_png)

    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
