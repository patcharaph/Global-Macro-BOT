"""Backtest results page — FlowMacro vs 60/40 and SPY benchmarks."""
from datetime import date
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Backtest — FlowMacro", layout="wide")
st.title("Backtest: FlowMacro vs 60/40 & SPY")


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=3600)
def load_backtest() -> dict | None:
    try:
        r = _db().table("backtest_runs").select("*").order("run_date", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_curve(series_id: str) -> pd.Series:
    try:
        from flowmacro.data.store import read_series
        return read_series(series_id, start="2000-01-01")
    except Exception:
        return pd.Series(dtype=float)


result = load_backtest()

if result is None:
    st.info("ยังไม่มีผล backtest — รัน `python scripts/run_backtest.py`")
    st.stop()

# ── Metrics ───────────────────────────────────────────────────────────────────
p_start = result.get("period_start") or "—"
p_end   = result.get("period_end")   or "—"
st.caption(f"Run date: {result.get('run_date','—')}  |  Period: {p_start} → {p_end}")

c1, c2, c3, c4 = st.columns(4)
sharpe   = result.get("sharpe_ratio")
b_sharpe = result.get("benchmark_sharpe")
ret      = result.get("annual_return")
b_ret    = result.get("benchmark_return")
dd       = result.get("max_drawdown")

c1.metric("Sharpe Ratio",  f"{sharpe:.2f}"  if sharpe is not None else "—",
          delta=f"vs 60/40: {b_sharpe:.2f}" if b_sharpe is not None else None)
c2.metric("Max Drawdown",  f"{dd:.1f}%"     if dd     is not None else "—",
          delta_color="inverse")
c3.metric("Total Return",  f"{ret:.1f}%"    if ret    is not None else "—",
          delta=f"vs 60/40: {b_ret:.1f}%" if b_ret is not None else None)

# Branch B pass/fail criteria
_PASS_SHARPE = 0.7
_PASS_DD     = 25.0
with c4:
    st.markdown("**Branch B criteria**")
    if sharpe is not None:
        icon = "✅" if sharpe >= _PASS_SHARPE else "❌"
        st.caption(f"{icon} Sharpe ≥ 0.7: {sharpe:.2f}")
    if dd is not None:
        icon = "✅" if dd <= _PASS_DD else "❌"
        st.caption(f"{icon} Max DD ≤ 25%: {dd:.1f}%")
    if result.get("outperforms_benchmark") is not None:
        icon = "✅" if result["outperforms_benchmark"] else "❌"
        st.caption(f"{icon} Beats benchmark")

if result.get("outperforms_benchmark") is False:
    st.warning("FlowMacro underperforms 60/40 — confidence threshold may need tuning")

st.divider()

# ── Equity Curves ─────────────────────────────────────────────────────────────
st.subheader("Equity Curve (normalised to 100)")

strategy_curve  = load_curve("equity_curve")
benchmark_curve = load_curve("equity_curve_benchmark")

if strategy_curve.empty and benchmark_curve.empty:
    st.info("ไม่มีข้อมูล equity curve — รัน `python scripts/run_backtest.py` อีกครั้ง")
else:
    fig = go.Figure()

    if not strategy_curve.empty:
        fig.add_trace(go.Scatter(
            x=strategy_curve.index, y=strategy_curve.values,
            name="FlowMacro",
            line=dict(color="#2ecc71", width=2),
        ))

    if not benchmark_curve.empty:
        fig.add_trace(go.Scatter(
            x=benchmark_curve.index, y=benchmark_curve.values,
            name="60/40 Benchmark",
            line=dict(color="#3498db", width=2, dash="dot"),
        ))

    fig.update_layout(
        yaxis_title="Portfolio Value (start = 100)",
        xaxis_title="",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=40),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
    st.plotly_chart(fig, use_container_width=True)

st.caption("Transaction costs: 0.05% per trade + $1 fixed fee  |  60/40 rebalances quarterly")
