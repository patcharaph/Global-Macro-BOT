"""Backtest results page — V3 Walk-Forward (current) and V2B legacy."""
from datetime import date, datetime
import math
import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Backtest — FlowMacro", layout="wide")
st.title("Backtest Results")
st.caption("V3 = softmax blend (current)  •  V2B = hard classify (legacy, before Jun 2026)")
st.info(
    "FlowMacro เป็น **Global Macro low-risk** strategy (80% invested, 20% cash, กระจายทั่วโลก) "
    "— เทียบ SPY โดยตรงไม่ยุติธรรม เพราะ SPY คือ 100% US equity ไม่มี hedge  "
    "เกณฑ์ที่เหมาะสมคือ **Sharpe ratio** และ **Max Drawdown** ไม่ใช่ total return",
    icon="ℹ️",
)

tab_v3, tab_v2b = st.tabs(["V3 — Current (Walk-Forward)", "V2B — Legacy (before Jun 2026)"])


# ── Shared helpers ────────────────────────────────────────────────────────────
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


@st.cache_data(ttl=3600)
def load_v3_wf() -> pd.DataFrame | None:
    csv_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "backtest_v3_walkforward.csv")
    )
    try:
        return pd.read_csv(csv_path) if os.path.exists(csv_path) else None
    except Exception:
        return None


def _cagr(total_pct: float | None, start: str, end: str) -> float | None:
    if total_pct is None or not start or not end or start == "—" or end == "—":
        return None
    try:
        years = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
        return (math.pow(1 + total_pct / 100, 1 / years) - 1) * 100 if years > 0 else None
    except Exception:
        return None


def _period_return(curve: pd.Series, years: float | None) -> float | None:
    if curve.empty:
        return None
    curve = curve[curve.index.dayofweek < 5]
    if curve.empty:
        return None
    end_date = curve.index[-1]
    start_date = pd.Timestamp(end_date.year, 1, 2) if years is None else \
        end_date - pd.DateOffset(years=int(years), months=int((years % 1) * 12))
    idx = curve.index.searchsorted(start_date, side="left")
    if idx >= len(curve):
        return None
    start_val = curve.iloc[idx]
    return (curve.iloc[-1] / start_val - 1) * 100 if start_val != 0 else None


# ── Tab V3 ────────────────────────────────────────────────────────────────────
with tab_v3:
    wf_df = load_v3_wf()
    if wf_df is None:
        st.info("No V3 backtest data — run `python scripts/backtest_v3.py`")
    else:
        st.caption("Walk-Forward: 5Y train / 2Y test / 1Y roll  •  11 windows 2010–2026")

        mean_v2b = wf_df["v2b_sharpe"].mean()
        mean_v3  = wf_df["v3_sharpe"].mean()
        mean_v3f = wf_df["v3f_sharpe"].mean()
        mean_dd_v2b = wf_df["v2b_dd"].mean()
        mean_dd_v3  = wf_df["v3_dd"].mean()
        mean_dd_v3f = wf_df["v3f_dd"].mean()

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("V2B mean OOS Sharpe", f"{mean_v2b:.2f}",
                   help="Baseline: rule-based hard classify")
        mc2.metric("V3 mean OOS Sharpe", f"{mean_v3:.2f}",
                   delta=f"{mean_v3 - mean_v2b:+.2f} vs V2B")
        mc3.metric("V3F mean OOS Sharpe", f"{mean_v3f:.2f}",
                   delta=f"{mean_v3f - mean_v2b:+.2f} vs V2B")

        md1, md2, md3 = st.columns(3)
        md1.metric("V2B mean MaxDD", f"{mean_dd_v2b:.1f}%")
        md2.metric("V3 mean MaxDD", f"{mean_dd_v3:.1f}%",
                   delta=f"{mean_dd_v3 - mean_dd_v2b:+.1f}%", delta_color="inverse")
        md3.metric("V3F mean MaxDD", f"{mean_dd_v3f:.1f}%",
                   delta=f"{mean_dd_v3f - mean_dd_v2b:+.1f}%", delta_color="inverse")

        short_labels = [w.split(":")[0] for w in wf_df["window"]]
        fig_wf = go.Figure()
        for col, name, color in [
            ("v2b_sharpe", "V2B (legacy)", "#8888aa"),
            ("v3_sharpe",  "V3",           "#00ff88"),
            ("v3f_sharpe", "V3F",          "#00d4ff"),
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
            barmode="group", height=300,
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


# ── Tab V2B ───────────────────────────────────────────────────────────────────
with tab_v2b:
    st.warning("**V2B Legacy** — strategy ก่อน V3 upgrade (มิ.ย. 2026) ใช้ hard classify ไม่มี softmax blend")

    result = load_backtest()
    if result is None:
        st.info("ยังไม่มีผล backtest — รัน `python scripts/run_backtest.py`")
        st.stop()

    p_start = result.get("period_start") or "—"
    p_end   = result.get("period_end")   or "—"
    st.caption(f"Run date: {result.get('run_date','—')}  |  Period: {p_start} → {p_end}")

    sharpe   = result.get("sharpe_ratio")
    b_sharpe = result.get("benchmark_sharpe")
    ret      = result.get("annual_return")
    b_ret    = result.get("benchmark_return")
    dd       = result.get("max_drawdown")
    cagr     = _cagr(ret,   p_start, p_end)
    b_cagr   = _cagr(b_ret, p_start, p_end)

    c1, c2, c3, c4, c5 = st.columns(5)

    # Fixed delta: compute difference so arrow direction is meaningful
    c1.metric("Sharpe Ratio", f"{sharpe:.2f}" if sharpe is not None else "—",
              delta=f"{sharpe - b_sharpe:+.2f} vs 60/40" if (sharpe and b_sharpe) else None,
              help="Return ÷ Risk  •  > 1.0 ดีมาก  •  > 0.7 ผ่านเกณฑ์")
    c2.metric("Max Drawdown", f"{dd:.1f}%" if dd is not None else "—",
              delta_color="inverse",
              help="ยิ่งต่ำยิ่งดี — เกณฑ์ผ่าน: ≤ 25%")
    c3.metric("CAGR", f"{cagr:.1f}%" if cagr is not None else "—",
              delta=f"{cagr - b_cagr:+.1f}% vs 60/40" if (cagr and b_cagr) else None,
              help="Compound Annual Growth Rate")
    c4.metric("Total Return", f"{ret:.1f}%" if ret is not None else "—",
              delta=f"{ret - b_ret:+.1f}% vs 60/40" if (ret and b_ret) else None,
              help="ผลตอบแทนสะสมตลอด period")

    with c5:
        st.markdown("**Branch B criteria**")
        _PASS_SHARPE, _PASS_DD = 0.7, 25.0
        if sharpe is not None:
            st.caption(f"{'✅' if sharpe >= _PASS_SHARPE else '❌'} Sharpe ≥ 0.7: {sharpe:.2f}")
        if dd is not None:
            st.caption(f"{'✅' if dd <= _PASS_DD else '❌'} Max DD ≤ 25%: {dd:.1f}%")
        if result.get("outperforms_benchmark") is not None:
            st.caption(f"{'✅' if result['outperforms_benchmark'] else '❌'} Beats 60/40")

    st.divider()

    # Equity curves
    st.subheader("Equity Curve (normalised to 100)")
    strategy_curve  = load_curve("equity_curve")
    benchmark_curve = load_curve("equity_curve_benchmark")
    spy_curve       = load_curve("equity_curve_spy")

    if strategy_curve.empty and benchmark_curve.empty:
        st.info("ไม่มีข้อมูล equity curve — รัน `python scripts/run_backtest.py` อีกครั้ง")
    else:
        fig = go.Figure()
        for curve, name, color, dash in [
            (strategy_curve,  "FlowMacro V2B",  "#00ff88", "solid"),
            (benchmark_curve, "60/40 Benchmark","#3498db", "dot"),
            (spy_curve,       "SPY Buy & Hold", "#8888aa", "dash"),
        ]:
            if not curve.empty:
                fig.add_trace(go.Scatter(
                    x=curve.index, y=curve.values, name=name,
                    line=dict(color=color, width=2, dash=dash),
                ))
        fig.update_layout(
            yaxis_title="Value (start = 100)", height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=10, b=40),
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "SPY ดูสูงกว่าเพราะเป็น 100% US equity — FlowMacro กระจายความเสี่ยงทั่วโลก  "
            "Transaction costs: 0.1% round-trip"
        )

    st.divider()

    # Period returns
    st.subheader("Period Returns")
    _PERIODS = [("YTD", None), ("1Y", 1), ("2Y", 2), ("3Y", 3), ("5Y", 5), ("10Y", 10)]
    _SERIES  = {"FlowMacro V2B": strategy_curve,
                "60/40": benchmark_curve, "SPY": spy_curve}
    _COLORS  = {"FlowMacro V2B": "#00ff88", "60/40": "#3498db", "SPY": "#8888aa"}

    rows: dict[str, list] = {label: [] for label in _SERIES}
    for _, yrs in _PERIODS:
        for label, curve in _SERIES.items():
            rows[label].append(_period_return(curve, yrs))

    if all(all(v is None for v in vals) for vals in rows.values()):
        st.info("ไม่มีข้อมูล equity curve สำหรับคำนวณ period returns")
    else:
        period_labels = [p for p, _ in _PERIODS]
        fig_pr = go.Figure()
        for label, vals in rows.items():
            fig_pr.add_trace(go.Bar(
                name=label, x=period_labels,
                y=[v if v is not None else 0 for v in vals],
                text=[f"{v:.1f}%" if v is not None else "N/A" for v in vals],
                textposition="outside", marker_color=_COLORS[label], opacity=0.9,
            ))
        fig_pr.update_layout(
            barmode="group", yaxis_title="Return (%)", height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30, b=40),
            yaxis=dict(zeroline=True, zerolinecolor="rgba(255,255,255,0.2)"),
        )
        fig_pr.update_xaxes(showgrid=False)
        fig_pr.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
        st.plotly_chart(fig_pr, use_container_width=True)

        table_data = {"Period": period_labels}
        for label, vals in rows.items():
            table_data[label] = [f"{v:.1f}%" if v is not None else "N/A" for v in vals]
        st.dataframe(pd.DataFrame(table_data).set_index("Period"), use_container_width=True)
