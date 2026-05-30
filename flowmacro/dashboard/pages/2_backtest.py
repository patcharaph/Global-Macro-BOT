"""Backtest results page — shows FlowMacro vs 60/40 benchmark."""
from datetime import date
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Backtest — FlowMacro", layout="wide")
st.title("Backtest: FlowMacro vs 60/40")


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
def load_equity_curve() -> pd.DataFrame:
    try:
        r = (
            _db().table("raw_series")
            .select("date, value")
            .eq("series_id", "equity_curve")
            .order("date")
            .execute()
        )
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")
    except Exception:
        return pd.DataFrame()


result = load_backtest()

if result is None:
    st.info(
        "ยังไม่มีผล backtest — รัน backtest ด้วย `python -m flowmacro.backtest.engine` "
        "แล้วบันทึกผลลง Supabase table `backtest_runs`"
    )
    st.stop()

# ── Metrics ──────────────────────────────────────────────────────────────────
st.caption(f"Run date: {result.get('run_date', '—')}  |  Period: {result.get('period_start', '—')} → {result.get('period_end', '—')}")

c1, c2, c3 = st.columns(3)
c1.metric("Sharpe Ratio",   f"{result.get('sharpe_ratio', 0):.2f}",   f"vs 60/40: {result.get('benchmark_sharpe', 0):.2f}")
c2.metric("Max Drawdown",   f"{result.get('max_drawdown', 0):.1f}%",  delta_color="inverse")
c3.metric("Annual Return",  f"{result.get('annual_return', 0):.1f}%", f"vs 60/40: {result.get('benchmark_return', 0):.1f}%")

outperforms = result.get("outperforms_benchmark")
if outperforms is False:
    st.warning("Out-of-sample Sharpe < 1.0 หรือ return ต่ำกว่า benchmark — ควร review strategy")

st.divider()

# ── Equity curve ─────────────────────────────────────────────────────────────
st.subheader("Equity Curve")
eq = load_equity_curve()
if eq.empty:
    st.info("ไม่มีข้อมูล equity curve — ต้องบันทึก series_id='equity_curve' ลง raw_series")
else:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=eq["value"], name="FlowMacro", line=dict(color="#2ecc71")))
    fig.update_layout(yaxis_title="Portfolio Value (normalized)", xaxis_title="", height=400, margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)

st.caption("Backtest uses walk-forward (train 10Y, test 5Y, roll 1Y) with transaction costs 0.15% + $1/trade")
