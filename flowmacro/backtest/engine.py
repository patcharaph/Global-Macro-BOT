import uuid
from datetime import date
import numpy as np
import pandas as pd
import vectorbt as vbt
from loguru import logger
from flowmacro.portfolio.allocator import get_weights


def weights_from_regimes(
    regime_series: pd.Series,
    tickers: list[str],
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Convert weekly regime signals to a daily weight DataFrame.
    Non-rebalancing days are NaN (vectorbt holds position, no order placed).
    """
    weights = pd.DataFrame(np.nan, index=price_index, columns=tickers)

    rebal_dates = regime_series.index.intersection(price_index)
    for date in rebal_dates:
        regime = regime_series.loc[date]
        w = get_weights(regime, tickers)
        for ticker in tickers:
            weights.loc[date, ticker] = w.get(ticker, 0.0)

    return weights


def _metrics(pf) -> dict:
    stats = pf.stats()
    return {
        "sharpe_ratio":      round(float(stats["Sharpe Ratio"]), 3),
        "max_drawdown_pct":  round(abs(float(stats["Max Drawdown [%]"])), 2),
        "total_return_pct":  round(float(stats["Total Return [%]"]), 2),
    }


def run_backtest(
    prices: pd.DataFrame,
    regime_series: pd.Series,
    init_cash: float = 3000.0,
) -> dict:
    """
    prices:        daily close prices (must include SPY and TLT for benchmark)
    regime_series: weekly pd.Series of regime strings (GOLDILOCKS/REFLATION/…)
    Returns dict with strategy and benchmark_60_40 metrics.
    """
    tickers = list(prices.columns)
    weights = weights_from_regimes(regime_series, tickers, prices.index)

    logger.info(f"Backtest: {len(prices)} days, {len(regime_series)} regime signals")

    pf = vbt.Portfolio.from_orders(
        close=prices,
        size=weights,
        size_type="targetpercent",
        fees=0.0005,
        fixed_fees=1.0,
        init_cash=init_cash,
        freq="1D",
        group_by=True,
        cash_sharing=True,
    )

    # 60/40 benchmark — rebalance quarterly
    bench_prices = prices[["SPY", "TLT"]]
    bench_weights = pd.DataFrame(np.nan, index=prices.index, columns=["SPY", "TLT"])
    rebal_idx = prices.index[prices.index.is_quarter_end | (prices.index == prices.index[0])]
    bench_weights.loc[rebal_idx, "SPY"] = 0.60
    bench_weights.loc[rebal_idx, "TLT"] = 0.40

    bench_pf = vbt.Portfolio.from_orders(
        close=bench_prices,
        size=bench_weights,
        size_type="targetpercent",
        fees=0.0005,
        fixed_fees=1.0,
        init_cash=init_cash,
        freq="1D",
        group_by=True,
        cash_sharing=True,
    )

    equity = pf.value()
    equity_norm = (equity / equity.iloc[0] * 100).rename("equity_curve")

    return {
        "strategy":        _metrics(pf),
        "benchmark_60_40": _metrics(bench_pf),
        "equity_curve":    equity_norm,
    }


def save_backtest(result: dict, client=None) -> str:
    """Save backtest result to Supabase. Returns run_id (UUID)."""
    if client is None:
        from flowmacro.data.store import _client
        client = _client()

    run_id = str(uuid.uuid4())
    strat  = result["strategy"]
    bench  = result["benchmark_60_40"]

    row = {
        "run_id":               run_id,
        "run_date":             str(date.today()),
        "sharpe_ratio":         strat["sharpe_ratio"],
        "max_drawdown":         strat["max_drawdown_pct"],
        "annual_return":        strat["total_return_pct"],
        "benchmark_sharpe":     bench["sharpe_ratio"],
        "benchmark_return":     bench["total_return_pct"],
        "outperforms_benchmark": strat["total_return_pct"] > bench["total_return_pct"],
    }
    client.table("backtest_runs").upsert(row).execute()

    equity: pd.Series | None = result.get("equity_curve")
    if equity is not None and not equity.empty:
        rows = [
            {"series_id": "equity_curve", "date": str(idx.date()), "value": float(val)}
            for idx, val in equity.items()
            if pd.notna(val)
        ]
        client.table("raw_series").upsert(rows, on_conflict="series_id,date").execute()

    return run_id
