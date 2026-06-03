"""Backtest results page — FlowMacro vs 60/40 and SPY benchmarks."""
from datetime import date, datetime
import math
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

c1, c2, c3, c4, c5 = st.columns(5)
sharpe   = result.get("sharpe_ratio")
b_sharpe = result.get("benchmark_sharpe")
ret      = result.get("annual_return")   # total return (naming in DB)
b_ret    = result.get("benchmark_return")
dd       = result.get("max_drawdown")

# ── Compute CAGR ──────────────────────────────────────────────────────────────
def _cagr(total_pct: float | None, start: str, end: str) -> float | None:
    if total_pct is None or not start or not end or start == "—" or end == "—":
        return None
    try:
        years = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
        return (math.pow(1 + total_pct / 100, 1 / years) - 1) * 100 if years > 0 else None
    except Exception:
        return None

cagr   = _cagr(ret,   p_start, p_end)
b_cagr = _cagr(b_ret, p_start, p_end)

c1.metric("Sharpe Ratio", f"{sharpe:.2f}" if sharpe is not None else "—",
          delta=f"vs 60/40: {b_sharpe:.2f}" if b_sharpe is not None else None,
          help="Return ÷ Risk (annualised)\n> 1.0 = ดีมาก  •  > 0.7 = ผ่านเกณฑ์  •  < 0 = แย่กว่า cash\n60/40 = SPY 60% + TLT 40% rebalance รายไตรมาส")
c2.metric("Max Drawdown", f"{dd:.1f}%" if dd is not None else "—",
          delta_color="inverse",
          help="การลดลงสูงสุดจาก peak ถึง trough ตลอด backtest period\nยิ่งต่ำยิ่งดี — เกณฑ์ผ่าน: ≤ 25%")
c3.metric("Annual Return (CAGR)", f"{cagr:.1f}%" if cagr is not None else "—",
          delta=f"vs 60/40: {b_cagr:.1f}%" if b_cagr is not None else None,
          help="Compound Annual Growth Rate — ผลตอบแทนทบต้นเฉลี่ยต่อปี\nสูตร: (1 + total_return)^(1/years) − 1")
c4.metric("Total Return", f"{ret:.1f}%" if ret is not None else "—",
          delta=f"vs 60/40: {b_ret:.1f}%" if b_ret is not None else None,
          help="ผลตอบแทนสะสมตลอด period (ไม่ใช่ต่อปี)\n60/40 Benchmark = SPY 60% + TLT 40%")

# Branch B pass/fail criteria
_PASS_SHARPE = 0.7
_PASS_DD     = 25.0
with c5:
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

st.caption("Transaction costs: 0.1% round-trip per rebalance  |  60/40 rebalances quarterly  |  Init capital: $3,000")
