"""Backtest results page — V3 Walk-Forward (current strategy)."""
from datetime import date, datetime
import math
import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Backtest — FlowMacro", layout="wide")
st.title("Backtest — V3 Walk-Forward Analysis")
st.caption(
    "V3 softmax blend (current strategy)  •  5Y train / 2Y test / 1Y roll  •  11 windows 2010–2026  •  "
    "FlowMacro = Global Macro low-risk — เกณฑ์วัดคือ Sharpe + MaxDD ไม่ใช่ total return vs SPY"
)


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=3600)
def load_v3_wf() -> pd.DataFrame | None:
    csv_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "backtest_v3_walkforward.csv")
    )
    try:
        return pd.read_csv(csv_path) if os.path.exists(csv_path) else None
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_backtest_legacy() -> dict | None:
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


@st.cache_data(ttl=3600)
def load_v3_curves() -> pd.DataFrame | None:
    """Load full equity curves from backtest_v3.csv (Date, is_v2b, is_v3, is_v3f, ...)."""
    csv_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "backtest_v3.csv")
    )
    try:
        if not os.path.exists(csv_path):
            return None
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        return df
    except Exception:
        return None


# ── V3 Walk-Forward (main) ────────────────────────────────────────────────────
wf_df = load_v3_wf()

if wf_df is None:
    st.info("No V3 backtest data — run `python scripts/backtest_v3.py`")
    st.stop()

mean_v2b    = wf_df["v2b_sharpe"].mean()
mean_v3     = wf_df["v3_sharpe"].mean()
mean_v3f    = wf_df["v3f_sharpe"].mean()
mean_dd_v2b = wf_df["v2b_dd"].mean()
mean_dd_v3  = wf_df["v3_dd"].mean()
mean_dd_v3f = wf_df["v3f_dd"].mean()

mc1, mc2, mc3 = st.columns(3)
mc1.metric("V2B mean OOS Sharpe", f"{mean_v2b:.2f}", help="Baseline: rule-based hard classify")
mc2.metric("V3 mean OOS Sharpe",  f"{mean_v3:.2f}",  delta=f"{mean_v3 - mean_v2b:+.2f} vs V2B")
mc3.metric("V3F mean OOS Sharpe", f"{mean_v3f:.2f}", delta=f"{mean_v3f - mean_v2b:+.2f} vs V2B")

md1, md2, md3 = st.columns(3)
md1.metric("V2B mean MaxDD", f"{mean_dd_v2b:.1f}%")
md2.metric("V3 mean MaxDD",  f"{mean_dd_v3:.1f}%",  delta=f"{mean_dd_v3 - mean_dd_v2b:+.1f}%",  delta_color="inverse")
md3.metric("V3F mean MaxDD", f"{mean_dd_v3f:.1f}%", delta=f"{mean_dd_v3f - mean_dd_v2b:+.1f}%", delta_color="inverse")

short_labels = [w.split(":")[0] for w in wf_df["window"]]
fig_wf = go.Figure()
for col, name, color in [
    ("v2b_sharpe", "V2B (baseline)", "#8888aa"),
    ("v3_sharpe",  "V3",            "#00ff88"),
    ("v3f_sharpe", "V3F",           "#00d4ff"),
]:
    fig_wf.add_trace(go.Bar(
        name=name, x=short_labels, y=wf_df[col],
        marker_color=color,
        hovertemplate=f"{name} %{{x}}: %{{y:.2f}}<extra></extra>",
    ))
fig_wf.add_hline(y=0.9, line=dict(color="rgba(255,204,0,0.5)", width=1, dash="dash"),
                 annotation_text="target 0.90",
                 annotation_font=dict(color="rgba(255,204,0,0.7)", size=9))
fig_wf.update_layout(
    barmode="group", height=320,
    margin=dict(l=10, r=10, t=10, b=60),
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(showgrid=False, tickangle=-30, tickfont=dict(size=9, family="monospace")),
    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.07)", title="Sharpe"),
    legend=dict(orientation="h", y=1.08, font=dict(size=10)),
)
st.plotly_chart(fig_wf, use_container_width=True, config={"displayModeBar": False})

with st.expander("Raw Walk-Forward Table", expanded=False):
    disp = wf_df.copy()
    disp.columns = ["Window", "V2B Sharpe", "V3 Sharpe", "V3F Sharpe",
                    "V2B DD%", "V3 DD%", "V3F DD%"]
    st.dataframe(disp.round(2), use_container_width=True, hide_index=True)

st.divider()

# ── V2B Legacy (collapsed) ────────────────────────────────────────────────────
with st.expander("V2B Legacy — equity curve (before Jun 2026)", expanded=False):
    st.warning("⚠️ แสดงผล V2B (legacy ก่อน V3 upgrade มิ.ย. 2026) — V3 results ดูที่ Walk-Forward Analysis ด้านบน")

    result = load_backtest_legacy()
    if result is None:
        st.info("ยังไม่มีผล — รัน `python scripts/run_backtest.py`")
    else:
        def _cagr(total_pct, start, end):
            try:
                years = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
                return (math.pow(1 + total_pct / 100, 1 / years) - 1) * 100 if years > 0 else None
            except Exception:
                return None

        p_start  = result.get("period_start") or "—"
        p_end    = result.get("period_end")   or "—"
        sharpe   = result.get("sharpe_ratio")
        b_sharpe = result.get("benchmark_sharpe")
        ret      = result.get("annual_return")
        b_ret    = result.get("benchmark_return")
        dd       = result.get("max_drawdown")
        cagr     = _cagr(ret,   p_start, p_end) if ret else None
        b_cagr   = _cagr(b_ret, p_start, p_end) if b_ret else None

        st.caption(f"Period: {p_start} → {p_end}  •  V3 OOS mean (WF): Sharpe 1.06, MaxDD 8.8%")

        # V3 OOS summary from WF CSV for side-by-side comparison
        _v3_sharpe = wf_df["v3_sharpe"].mean() if wf_df is not None else None
        _v3_dd     = wf_df["v3_dd"].mean()     if wf_df is not None else None

        st.markdown("**Sharpe Ratio**")
        sc1, sc2 = st.columns(2)
        sc1.metric("V2B", f"{sharpe:.2f}" if sharpe else "—", help="Full period IS backtest")
        sc2.metric("V3",  f"{_v3_sharpe:.2f}" if _v3_sharpe else "—",
                   delta=f"{_v3_sharpe - sharpe:+.2f} vs V2B" if (_v3_sharpe and sharpe) else None,
                   help="Mean OOS Sharpe across 11 WF windows")

        st.markdown("**Max Drawdown**")
        dc1, dc2 = st.columns(2)
        dc1.metric("V2B", f"{dd:.1f}%" if dd else "—", delta_color="inverse")
        dc2.metric("V3",  f"{_v3_dd:.1f}%" if _v3_dd else "—",
                   delta=f"{_v3_dd - dd:+.1f}% vs V2B" if (_v3_dd and dd) else None,
                   delta_color="inverse", help="Mean OOS MaxDD across 11 WF windows")

        strategy_curve  = load_curve("equity_curve")
        benchmark_curve = load_curve("equity_curve_benchmark")
        spy_curve       = load_curve("equity_curve_spy")
        v3_curves_df    = load_v3_curves()

        fig = go.Figure()
        # V3 from CSV (most important — show first so it's on top)
        if v3_curves_df is not None and "is_v3" in v3_curves_df.columns:
            fig.add_trace(go.Scatter(
                x=v3_curves_df.index, y=v3_curves_df["is_v3"],
                name="FlowMacro V3 (current)",
                line=dict(color="#00ff88", width=2.5),
            ))
        # V2B from Supabase
        if not strategy_curve.empty:
            fig.add_trace(go.Scatter(
                x=strategy_curve.index, y=strategy_curve.values,
                name="FlowMacro V2B (legacy)",
                line=dict(color="#ffcc00", width=1.5, dash="dot"),
            ))
        # Benchmarks
        if not benchmark_curve.empty:
            fig.add_trace(go.Scatter(
                x=benchmark_curve.index, y=benchmark_curve.values,
                name="60/40",
                line=dict(color="#3498db", width=1.5, dash="dot"),
            ))
        if not spy_curve.empty:
            fig.add_trace(go.Scatter(
                x=spy_curve.index, y=spy_curve.values,
                name="SPY",
                line=dict(color="#8888aa", width=1.5, dash="dash"),
            ))

        if len(fig.data) > 0:
            fig.update_layout(
                yaxis_title="Value (start=100)", height=380,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified",
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=40),
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("SPY สูงกว่าเพราะ 100% US equity — FlowMacro กระจายทั่วโลก มี cash buffer 20%")
        else:
            st.info("ไม่มีข้อมูล equity curve")
