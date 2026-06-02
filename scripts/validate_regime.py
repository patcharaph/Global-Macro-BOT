#!/usr/bin/env python3
"""
Branch A — Regime accuracy validation (2005–present).

Ground truth:
  B) NBER recession dates (objective anchor)
  C) Asset price behavior sanity check (SPY/TLT/GLD/DBC/UUP avg returns per regime)

Pass criteria: 6 key episodes correct + lag ≤ 2 months each.

Output:
  scripts/validate_regime.csv  — daily regime, confidence, growth/inflation scores
  scripts/validate_regime.png  — regime timeline + asset return heatmap
"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from loguru import logger

from flowmacro.data.store import read_series
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series

_START = "2005-01-01"
_OUT_DIR = Path(__file__).parent

# NBER official recession dates (used as reference bands on chart)
_NBER = [
    ("2007-12-01", "2009-06-30"),  # GFC
    ("2020-02-01", "2020-04-30"),  # COVID
]

# (label, window_start, window_end, expected_regime)
_EPISODES = [
    ("GFC peak",       "2008-09-01", "2009-03-31", "DEFLATION"),
    ("Recovery",       "2010-06-01", "2011-06-30", "REFLATION"),
    ("Goldilocks",     "2013-01-01", "2015-12-31", "GOLDILOCKS"),
    ("COVID crash",    "2020-03-01", "2020-04-30", "DEFLATION"),
    ("Reopening",      "2021-06-01", "2022-06-30", "REFLATION"),
    ("Rate hike peak", "2022-09-01", "2023-09-30", "STAGFLATION"),
]
_LAG_LIMIT_MONTHS = 2

_COLORS = {
    "GOLDILOCKS":    "#2ecc71",
    "REFLATION":     "#f39c12",
    "STAGFLATION":   "#e74c3c",
    "DEFLATION":     "#3498db",
    "TRANSITIONING": "#bdc3c7",
}

_PRICE_TICKERS = ["SPY", "TLT", "GLD", "DBC", "UUP"]


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_indicators() -> pd.DataFrame:
    """Read and normalize all indicators from Supabase → daily DataFrame (0-100)."""
    normalized: dict[str, pd.Series] = {}
    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_START)
            if raw.empty:
                logger.warning(f"No data: {ind.name} ({ind.series_id})")
                continue
            daily = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
            logger.info(f"  {ind.name}: {len(raw)} rows")
        except Exception as exc:
            logger.warning(f"  Skipped {ind.name}: {exc}")
    return pd.DataFrame(normalized)


def _load_prices() -> pd.DataFrame:
    """Read price tickers from Supabase for asset behavior sanity check."""
    frames: dict[str, pd.Series] = {}
    for ticker in _PRICE_TICKERS:
        try:
            s = read_series(ticker, start=_START)
            if not s.empty:
                frames[ticker] = s
        except Exception:
            pass
    return pd.DataFrame(frames)


# ── Validation logic ──────────────────────────────────────────────────────────

def _check_episodes(regime_series: pd.Series) -> list[dict]:
    results = []
    for label, start, end, expected in _EPISODES:
        window = regime_series[start:end]
        if window.empty:
            results.append({"episode": label, "expected": expected,
                             "pass": False, "note": "no data in window"})
            continue

        dominant = window.value_counts().idxmax()
        pct = (window == expected).mean() * 100
        match = window[window == expected]

        if match.empty:
            results.append({
                "episode": label, "expected": expected, "dominant": dominant,
                "pct_match": round(pct, 1), "lag_months": None, "pass": False,
                "note": f"never reached {expected} — dominant={dominant} ({pct:.0f}%)",
            })
        else:
            first_match = match.index[0]
            lag_months = (first_match - pd.Timestamp(start)).days / 30
            passed = lag_months <= _LAG_LIMIT_MONTHS
            results.append({
                "episode": label, "expected": expected, "dominant": dominant,
                "pct_match": round(pct, 1), "lag_months": round(lag_months, 1),
                "pass": passed,
                "note": (f"first {expected}: {first_match.date()} "
                         f"(lag {lag_months:.1f}mo, {pct:.0f}% of window)"),
            })
    return results


def _asset_returns_by_regime(prices: pd.DataFrame,
                              regime_series: pd.Series) -> pd.DataFrame:
    """Average monthly return per asset grouped by regime."""
    if prices.empty:
        return pd.DataFrame()
    monthly_ret = prices.resample("ME").last().pct_change() * 100
    regime_monthly = regime_series.resample("ME").last()
    aligned = monthly_ret.join(regime_monthly.rename("regime"), how="inner").dropna(subset=["regime"])
    available = [t for t in _PRICE_TICKERS if t in aligned.columns]
    return aligned.groupby("regime")[available].mean().round(2)


# ── Chart ─────────────────────────────────────────────────────────────────────

def _plot(regime_series: pd.Series, returns_by_regime: pd.DataFrame,
          out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(18, 10),
                             gridspec_kw={"height_ratios": [3, 2]})
    fig.suptitle("FlowMacro — Regime Validation 2005–present", fontsize=14, fontweight="bold")

    # Top: regime timeline
    ax1 = axes[0]
    dates = regime_series.index
    seg_start = dates[0]
    prev = regime_series.iloc[0]

    for dt, regime in regime_series.items():
        if regime != prev:
            ax1.axvspan(seg_start, dt, alpha=0.4,
                        color=_COLORS.get(prev, "#ffffff"), linewidth=0)
            seg_start = dt
            prev = regime
    ax1.axvspan(seg_start, dates[-1], alpha=0.4,
                color=_COLORS.get(prev, "#ffffff"), linewidth=0)

    # NBER recession hatching
    for i, (rec_start, rec_end) in enumerate(_NBER):
        ax1.axvspan(pd.Timestamp(rec_start), pd.Timestamp(rec_end),
                    alpha=0.18, color="black", hatch="///", linewidth=0,
                    label="NBER Recession" if i == 0 else None)

    ax1.set_xlim(dates[0], dates[-1])
    ax1.set_yticks([])
    ax1.set_ylabel("Regime")
    ax1.set_title("Regime Timeline vs NBER Recessions (hatched)")
    legend_patches = [mpatches.Patch(color=c, alpha=0.6, label=r)
                      for r, c in _COLORS.items()]
    legend_patches.append(mpatches.Patch(facecolor="gray", alpha=0.3,
                                         hatch="///", label="NBER Recession"))
    ax1.legend(handles=legend_patches, loc="upper left", fontsize=8, ncol=3)

    # Bottom: avg monthly returns by regime
    ax2 = axes[1]
    if not returns_by_regime.empty:
        regimes_present = [r for r in _COLORS if r in returns_by_regime.index]
        tickers = [t for t in _PRICE_TICKERS if t in returns_by_regime.columns]
        x = range(len(tickers))
        width = 0.15
        for i, regime in enumerate(regimes_present):
            vals = [returns_by_regime.loc[regime, t] if t in returns_by_regime.columns else 0
                    for t in tickers]
            offset = (i - len(regimes_present) / 2) * width
            ax2.bar([xi + offset for xi in x], vals, width,
                    color=_COLORS[regime], alpha=0.75, label=regime)
        ax2.axhline(0, color="black", linewidth=0.8)
        ax2.set_xticks(list(x))
        ax2.set_xticklabels(tickers)
        ax2.set_ylabel("Avg Monthly Return (%)")
        ax2.set_title("Asset Behavior by Regime — sanity check (C)")
        ax2.legend(fontsize=8)

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    logger.info(f"Chart saved → {out_path}")
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=== Branch A: Regime Accuracy Validation ===")

    # 1. Load + normalize indicators
    logger.info("Loading indicators from Supabase...")
    norm_df = _load_indicators()
    if len(norm_df.columns) < 5:
        logger.error(f"Only {len(norm_df.columns)} indicators loaded — aborting")
        return

    # 2. Compute growth/inflation scores + classify with hysteresis
    logger.info(f"Classifying {len(norm_df)} dates with {len(norm_df.columns)} indicators...")
    scores = compute_scores(norm_df)
    scores = scores.dropna(how="all")
    classified = classify_series(scores)
    regime_series = classified["regime"]

    dist = regime_series.value_counts()
    logger.info(f"Regime distribution:\n{dist.to_string()}")

    # 3. Save CSV
    out_csv = _OUT_DIR / "validate_regime.csv"
    classified.to_csv(out_csv)
    logger.info(f"CSV → {out_csv}")

    # 4. Load prices for asset behavior check (C)
    logger.info("Loading prices for asset behavior check...")
    prices = _load_prices()
    returns_by_regime = _asset_returns_by_regime(prices, regime_series)
    if not returns_by_regime.empty:
        logger.info(f"Avg monthly returns by regime:\n{returns_by_regime.to_string()}")

    # 5. Episode validation (B: NBER ground truth)
    print("\n" + "=" * 65)
    print("EPISODE VALIDATION  (pass = expected regime within 2 months)")
    print("=" * 65)
    results = _check_episodes(regime_series)
    passed = sum(r["pass"] for r in results)

    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}]  {r['episode']:20s}  {r['note']}")

    print("-" * 65)
    print(f"  Score: {passed}/{len(results)} episodes")

    if passed == len(_EPISODES):
        verdict = "VALIDATION PASSED -- proceed to Branch B"
    elif passed >= len(_EPISODES) - 1:
        verdict = "MARGINAL -- tune confidence threshold (Step D) then re-run"
    else:
        verdict = "VALIDATION FAILED -- tune weights (Step A) or threshold (Step D)"
    print(f"\n  {verdict}\n")

    # 6. Chart
    out_png = _OUT_DIR / "validate_regime.png"
    _plot(regime_series, returns_by_regime, out_png)
    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
