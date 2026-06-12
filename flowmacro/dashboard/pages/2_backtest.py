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


@st.cache_data(ttl=300)
def load_ml_shadow_bt() -> dict:
    try:
        rows = _db().table("regime_history_ml").select(
            "run_date,ml_regime,rb_regime,agrees,ml_confidence"
        ).order("run_date").execute().data
        if not rows:
            return {"active": True, "n_weeks": 0, "rows": []}
        n = len(rows)
        return {
            "active":         True,
            "n_weeks":        n,
            "latest":         rows[-1],
            "agreement_rate": sum(1 for r in rows if r["agrees"]) / n * 100,
            "rows":           rows,
        }
    except Exception:
        return {"active": False, "n_weeks": 0, "rows": []}


@st.cache_data(ttl=300)
def load_ab_comparison() -> dict:
    """Load Portfolio A and B values for live comparison."""
    try:
        from flowmacro.data.store import read_series
        pa = read_series("paper_total_value", start="2026-06-01").sort_index()
        pb_rows = _db().table("paper_portfolio_ml").select(
            "date,portfolio_value,period_return,ml_regime,blend_weights"
        ).order("date").execute().data
        return {"pa": pa, "pb_rows": pb_rows}
    except Exception:
        return {"pa": pd.Series(dtype=float), "pb_rows": []}


@st.cache_data(ttl=3600)
def load_ml_blend_backtest() -> pd.DataFrame | None:
    csv_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "backtest_ml_blend.csv")
    )
    try:
        if not os.path.exists(csv_path):
            return None
        df = pd.read_csv(csv_path, parse_dates=["date"])
        return df
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_benchmarks_bt(start: str, end: str) -> dict[str, pd.Series]:
    """Download SPY and AGG weekly closes for benchmark computation."""
    import yfinance as yf
    result: dict[str, pd.Series] = {}
    for tk in ["SPY", "AGG"]:
        try:
            df = yf.download(tk, start=start, end=end, progress=False, auto_adjust=True)
            if not df.empty:
                result[tk] = df["Close"].squeeze().dropna()
        except Exception:
            pass
    return result


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

# ── ML-blend OOS Backtest (2020–2026) ─────────────────────────────────────────
st.subheader("ML-blend vs Rule-based — OOS Simulation (2020–2026)")
st.caption(
    "XGBoost 30% + Rule-based 70% vs Pure rule-based V3  •  "
    "ไม่มี momentum filter / vol targeting — apples-to-apples  •  "
    "XGBoost trained on NBER 2000–2024 (partial in-sample overlap)"
)

_mlbt = load_ml_blend_backtest()
if _mlbt is not None and not _mlbt.empty:
    _bt_start = str(_mlbt["date"].iloc[0].date())
    _bt_end   = str(_mlbt["date"].iloc[-1].date())

    # ── Benchmark: SPY + 60/40 ────────────────────────────────────────────────
    _bm = load_benchmarks_bt(_bt_start, _bt_end)
    _spy_raw = _bm.get("SPY", pd.Series(dtype=float))
    _agg_raw = _bm.get("AGG", pd.Series(dtype=float))

    def _weekly_cum(price_series: pd.Series, dates: pd.Series) -> pd.Series:
        """Compute cumulative % return aligned to backtest dates."""
        if price_series.empty:
            return pd.Series([float("nan")] * len(dates), index=range(len(dates)))
        wk = price_series.reindex(dates, method="ffill")
        ret = wk.pct_change().fillna(0)
        return (((1 + ret).cumprod()) - 1) * 100

    _bt_dates = _mlbt["date"]
    _spy_cum  = _weekly_cum(_spy_raw, _bt_dates)
    _spy_ret_wk = _spy_raw.reindex(_bt_dates, method="ffill").pct_change().fillna(0) * 100

    _spy_tot = float(_spy_cum.iloc[-1]) if not _spy_cum.empty else float("nan")
    _spy_s   = float(_spy_ret_wk.mean() / _spy_ret_wk.std() * (52 ** 0.5)) if _spy_ret_wk.std() > 0 else float("nan")
    _spy_val = (1 + _spy_ret_wk / 100).cumprod()
    _spy_mdd = float(((_spy_val / _spy_val.cummax()) - 1).min() * 100)

    # 60/40 weekly return
    _agg_ret_wk = _agg_raw.reindex(_bt_dates, method="ffill").pct_change().fillna(0) * 100
    _r6040_wk   = 0.6 * _spy_ret_wk + 0.4 * _agg_ret_wk
    _r6040_val  = (1 + _r6040_wk / 100).cumprod()
    _r6040_cum  = (_r6040_val - 1) * 100
    _r6040_tot  = float(_r6040_cum.iloc[-1])
    _r6040_s    = float(_r6040_wk.mean() / _r6040_wk.std() * (52 ** 0.5)) if _r6040_wk.std() > 0 else float("nan")
    _r6040_mdd  = float(((_r6040_val / _r6040_val.cummax()) - 1).min() * 100)

    # ── Metrics table ─────────────────────────────────────────────────────────
    _rb_s   = _mlbt["rb_return_pct"].mean()    / _mlbt["rb_return_pct"].std()    * (52 ** 0.5)
    _ml_s   = _mlbt["ml_blend_ret_pct"].mean() / _mlbt["ml_blend_ret_pct"].std() * (52 ** 0.5)
    _rb_mdd = ((_mlbt["rb_value"]       / _mlbt["rb_value"].cummax())       - 1).min() * 100
    _ml_mdd = ((_mlbt["ml_blend_value"] / _mlbt["ml_blend_value"].cummax()) - 1).min() * 100
    _rb_tot = float(_mlbt["rb_cum_pct"].iloc[-1])
    _ml_tot = float(_mlbt["ml_cum_pct"].iloc[-1])
    _n_agree_bt   = (_mlbt["rb_regime"] == _mlbt["ml_regime"]).sum()
    _agree_bt_pct = _n_agree_bt / len(_mlbt) * 100

    _metrics_df = pd.DataFrame({
        "Strategy":    ["Rule-based V3", "ML-blend 30/70", "SPY", "60/40 (SPY+AGG)"],
        "Sharpe":      [f"{_rb_s:.2f}", f"{_ml_s:.2f}", f"{_spy_s:.2f}", f"{_r6040_s:.2f}"],
        "Max DD":      [f"{_rb_mdd:.1f}%", f"{_ml_mdd:.1f}%", f"{_spy_mdd:.1f}%", f"{_r6040_mdd:.1f}%"],
        "Total Return":[f"{_rb_tot:.1f}%", f"{_ml_tot:.1f}%", f"{_spy_tot:.1f}%", f"{_r6040_tot:.1f}%"],
    })
    st.dataframe(_metrics_df, use_container_width=True, hide_index=True)
    st.caption(f"Regime Agreement: {_agree_bt_pct:.0f}% ({_n_agree_bt}/{len(_mlbt)} สัปดาห์ที่ ML เห็นด้วย)")

    # ── Equity curve ──────────────────────────────────────────────────────────
    _fig_bt = go.Figure()
    _fig_bt.add_trace(go.Scatter(
        x=_bt_dates, y=_mlbt["rb_cum_pct"],
        name="Rule-based V3", mode="lines",
        line=dict(color="#00d4ff", width=2),
        hovertemplate="<b>Rule V3</b>: %{y:.1f}%<br>%{x|%Y-%m-%d}<extra></extra>",
    ))
    _fig_bt.add_trace(go.Scatter(
        x=_bt_dates, y=_mlbt["ml_cum_pct"],
        name="ML-blend 30/70", mode="lines",
        line=dict(color="#00ff88", width=2.5),
        hovertemplate="<b>ML-blend</b>: %{y:.1f}%<br>%{x|%Y-%m-%d}<extra></extra>",
    ))
    if not _spy_cum.empty:
        _fig_bt.add_trace(go.Scatter(
            x=_bt_dates, y=_spy_cum.values,
            name="SPY", mode="lines",
            line=dict(color="#ffcc00", width=1.5, dash="dot"),
            hovertemplate="<b>SPY</b>: %{y:.1f}%<br>%{x|%Y-%m-%d}<extra></extra>",
        ))
    if not _r6040_cum.empty:
        _fig_bt.add_trace(go.Scatter(
            x=_bt_dates, y=_r6040_cum.values,
            name="60/40 (SPY+AGG)", mode="lines",
            line=dict(color="#ff8844", width=1.5, dash="dash"),
            hovertemplate="<b>60/40</b>: %{y:.1f}%<br>%{x|%Y-%m-%d}<extra></extra>",
        ))
    _fig_bt.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.15)")
    _fig_bt.update_layout(
        height=360, hovermode="x unified",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=40, l=10, r=10),
        legend=dict(orientation="h", y=1.10, font=dict(size=11)),
        yaxis=dict(title="Cumulative Return (%)", showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(_fig_bt, use_container_width=True, config={"displayModeBar": False})

    with st.expander("รายสัปดาห์ — ML Regime vs Rule Regime", expanded=False):
        _bt_disp = _mlbt[["date", "rb_regime", "ml_regime", "ml_conf",
                           "rb_return_pct", "ml_blend_ret_pct",
                           "rb_cum_pct", "ml_cum_pct",
                           "growth_score", "inflation_score"]].copy()
        _bt_disp.columns = ["Date", "Rule Regime", "ML Regime", "ML Conf%",
                             "Rule Ret%", "ML Ret%",
                             "Rule Cum%", "ML Cum%",
                             "Growth", "Inflation"]
        _bt_disp = _bt_disp.iloc[::-1]
        st.dataframe(_bt_disp.round(2), use_container_width=True, hide_index=True)
else:
    st.info("ยังไม่มีข้อมูล — รัน `python scripts/backtest_ml_blend.py` ก่อน")

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

st.divider()

# ── ML Shadow Mode ────────────────────────────────────────────────────────────
st.subheader("ML Shadow Mode — XGBoost vs Rule-Based")
st.caption(
    "XGBoost (17 features, NBER-labeled 2000–2024) รันควบคู่กับ rule-based V3 ทุกศุกร์  "
    "•  ยังไม่กระทบ Portfolio A  •  26 สัปดาห์ครบ → ประเมิน graduation criteria ธ.ค. 2026"
)

_ml_bt = load_ml_shadow_bt()

_REGIME_COLOR_BT = {
    "GOLDILOCKS": "#00ff88", "REFLATION": "#ffcc00",
    "STAGFLATION": "#ff4466", "DEFLATION": "#00d4ff", "TRANSITIONING": "#8888aa",
}

if not _ml_bt.get("active"):
    st.warning("ML shadow data unavailable — check regime_history_ml table.")
elif _ml_bt["n_weeks"] == 0:
    st.info("Shadow mode active — predictions log every Friday. No data yet.")
else:
    _n_ml   = _ml_bt["n_weeks"]
    _rate   = _ml_bt["agreement_rate"]
    _rows   = _ml_bt["rows"]
    _latest = _ml_bt["latest"]

    # ─ Metric cards ───────────────────────────────────────────────────────────
    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
    _rate_color = "#00ff88" if _rate >= 70 else ("#ffcc00" if _rate >= 50 else "#ff4466")

    _mc1.metric("สัปดาห์ที่ติดตาม", f"{_n_ml} / 26",
                help="ต้องรอครบ 26 สัปดาห์ก่อน graduation evaluation ธ.ค. 2026")
    _mc2.metric("Agreement Rate", f"{_rate:.0f}%",
                delta="≥70% target" if _rate >= 70 else f"{_rate:.0f}% (need 70%)",
                delta_color="normal" if _rate >= 70 else "inverse",
                help="% สัปดาห์ที่ ML ทาย regime ตรงกับ rule-based")
    _mc3.metric("ML latest", _latest["ml_regime"],
                delta=f"conf {_latest['ml_confidence']:.1f}",
                help="XGBoost prediction สัปดาห์ล่าสุด")
    _mc4.metric("Rule-based latest", _latest["rb_regime"],
                help="สัปดาห์ล่าสุด: " + ("ML เห็นด้วย" if _latest["agrees"] else "ML ไม่ตรงกัน"))

    # ─ Agreement timeline chart ────────────────────────────────────────────────
    _dates  = [pd.to_datetime(r["run_date"]) for r in _rows]
    _agree  = [r["agrees"] for r in _rows]
    _ml_reg = [r["ml_regime"] for r in _rows]
    _rb_reg = [r["rb_regime"] for r in _rows]
    _ml_con = [r.get("ml_confidence", 0) for r in _rows]

    # Plotly range must be strings, not Timestamps
    _x_min = (_dates[0]  - pd.Timedelta(weeks=1)).strftime("%Y-%m-%d")
    _x_max = (_dates[-1] + pd.Timedelta(weeks=1)).strftime("%Y-%m-%d")

    fig_ml = go.Figure()

    # ML predictions — top row (y=1.5)
    fig_ml.add_trace(go.Scatter(
        x=_dates, y=[1.5] * len(_dates),
        mode="markers+text",
        marker=dict(
            size=22,
            color=[_REGIME_COLOR_BT.get(r, "#888") for r in _ml_reg],
            line=dict(width=2, color=["#00ff88" if a else "#ff4466" for a in _agree]),
            symbol="square",
        ),
        text=[r[:4] for r in _ml_reg],
        textfont=dict(size=8, color="#000", family="monospace"),
        textposition="middle center",
        hovertemplate="<b>ML: %{customdata[0]}</b><br>Conf: %{customdata[1]:.1f}<br>%{x|%Y-%m-%d}<extra></extra>",
        customdata=list(zip(_ml_reg, _ml_con)),
        name="ML (XGBoost)",
        showlegend=True,
    ))

    # Rule-based — bottom row (y=0.5)
    fig_ml.add_trace(go.Scatter(
        x=_dates, y=[0.5] * len(_dates),
        mode="markers+text",
        marker=dict(
            size=22,
            color=[_REGIME_COLOR_BT.get(r, "#888") for r in _rb_reg],
            line=dict(width=1, color="rgba(255,255,255,0.3)"),
            symbol="circle",
        ),
        text=[r[:4] for r in _rb_reg],
        textfont=dict(size=8, color="#000", family="monospace"),
        textposition="middle center",
        hovertemplate="<b>Rule: %{customdata}</b><br>%{x|%Y-%m-%d}<extra></extra>",
        customdata=_rb_reg,
        name="Rule-based V3",
        showlegend=True,
    ))

    fig_ml.update_layout(
        height=200,
        margin=dict(l=70, r=10, t=10, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False, tickformat="%b %d",
            color="rgba(0,212,255,0.6)",
            range=[_x_min, _x_max],
            type="date",
            autorange=False,
        ),
        yaxis=dict(
            range=[0, 2], showgrid=False,
            tickvals=[0.5, 1.5], ticktext=["Rule", "ML"],
            color="rgba(180,180,220,0.7)", tickfont=dict(family="monospace", size=10),
        ),
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
    )
    st.plotly_chart(fig_ml, use_container_width=True, config={"displayModeBar": False})
    st.caption(
        "สี่เหลี่ยม = ML  •  วงกลม = Rule-based  •  กรอบสีเขียว = ตรงกัน  •  กรอบสีแดง = ไม่ตรงกัน  "
        "•  สีใน = regime ที่ทาย (GOLD/REFL/STAG/DEFL)"
    )

    # ─ Per-regime breakdown ───────────────────────────────────────────────────
    with st.expander("Breakdown ตาม Regime", expanded=False):
        _breakdown = {}
        for r in _rows:
            rb = r["rb_regime"]
            if rb not in _breakdown:
                _breakdown[rb] = {"total": 0, "agree": 0}
            _breakdown[rb]["total"] += 1
            if r["agrees"]:
                _breakdown[rb]["agree"] += 1

        _bd_rows = []
        for reg, cnt in sorted(_breakdown.items()):
            agree_rate = cnt["agree"] / cnt["total"] * 100 if cnt["total"] > 0 else 0
            _bd_rows.append({
                "Regime":        reg,
                "สัปดาห์":      cnt["total"],
                "ML เห็นด้วย":  cnt["agree"],
                "Agreement %":  f"{agree_rate:.0f}%",
            })
        st.dataframe(pd.DataFrame(_bd_rows), use_container_width=True, hide_index=True)

    # ─ Graduation criteria ────────────────────────────────────────────────────
    with st.expander("Graduation Criteria (ธ.ค. 2026)", expanded=False):
        _n_agree_total = sum(1 for r in _rows if r["agrees"])
        _c1 = _rate >= 70
        _c3 = _n_ml >= 26
        _s_pass = "<span style='color:#00ff88'>PASS</span>"
        _s_wait = "<span style='color:#ffcc00'>รอ</span>"
        _c1_status = _s_pass if _c1 else _s_wait
        _c3_status = _s_pass if _c3 else f"<span style='color:#ffcc00'>{_n_ml}/26</span>"
        st.markdown(
            f"| Criteria | Status | ค่าปัจจุบัน |\n"
            f"|----------|--------|-------------|\n"
            f"| Agreement ≥ 70% / 26w | {_c1_status} | {_rate:.0f}% ({_n_agree_total}/{_n_ml} weeks) |\n"
            f"| NBER validation 5/6 regimes | {_s_pass} | validated offline |\n"
            f"| ครบ 26 สัปดาห์ live | {_c3_status} | {_n_ml} สัปดาห์ |",
            unsafe_allow_html=True,
        )

    # ─ Portfolio A vs B live comparison ──────────────────────────────────────
    st.divider()
    st.subheader("Portfolio A vs B — Live Performance")

    _ab = load_ab_comparison()
    _pa = _ab["pa"]
    _pb_rows = _ab["pb_rows"]

    _INIT = 3_000.0
    _pa_val = float(_pa.iloc[-1]) if not _pa.empty else _INIT
    _pa_ret = (_pa_val / _INIT - 1) * 100 if not _pa.empty else 0.0
    _pb_val = float(_pb_rows[-1]["portfolio_value"]) if _pb_rows else _INIT
    _pb_cumret = sum(r.get("period_return", 0) or 0 for r in _pb_rows)

    _ca, _cb = st.columns(2)
    _ca.metric("Portfolio A (Rule-based V3)",
               f"${_pa_val:,.2f}",
               delta=f"{_pa_ret:+.2f}% inception",
               help="V3 softmax blend — live ตั้งแต่ Jun 2026")
    _cb.metric("Portfolio B (ML-blend 30%)",
               f"${_pb_val:,.2f}",
               delta=f"{_pb_cumret:+.4f}% inception" if _pb_rows else "เพิ่งเริ่ม",
               help="30% XGBoost + 70% rule-based — virtual portfolio")

    # Weekly return log
    _log_rows = []
    _pa_sorted = _pa.sort_index()
    _pb_by_date = {r["date"]: r for r in _pb_rows}
    _shadow_by_date = {r["run_date"]: r for r in _rows}

    _pa_dates = list(_pa_sorted.index)
    for i in range(1, len(_pa_dates)):
        _dt = _pa_dates[i]
        _dt_str = str(_dt.date()) if hasattr(_dt, "date") else str(_dt)[:10]
        _pa_prev = float(_pa_sorted.iloc[i - 1])
        _pa_cur  = float(_pa_sorted.iloc[i])
        _pa_wret = (_pa_cur / _pa_prev - 1) * 100 if _pa_prev else 0.0

        _pb_r = _pb_by_date.get(_dt_str)
        _pb_wret = float(_pb_r["period_return"]) * 100 if _pb_r else None

        _sh = _shadow_by_date.get(_dt_str)
        _ml_reg  = _sh["ml_regime"]  if _sh else "—"
        _rb_reg  = _sh["rb_regime"]  if _sh else "—"
        _agrees  = _sh["agrees"]     if _sh else None

        _agrees_icon = "✓" if _agrees is True else ("✗" if _agrees is False else "—")

        _winner = "—"
        if _pb_wret is not None:
            if _pb_wret > _pa_wret:
                _winner = "B"
            elif _pa_wret > _pb_wret:
                _winner = "A"
            else:
                _winner = "Tie"

        _log_rows.append({
            "Date":        _dt_str,
            "ML Regime":   _ml_reg,
            "Rule Regime": _rb_reg,
            "Agree":       _agrees_icon,
            "A Return":    f"{_pa_wret:+.2f}%",
            "B Return":    f"{_pb_wret:+.2f}%" if _pb_wret is not None else "—",
            "Winner":      _winner,
        })

    if _log_rows:
        st.dataframe(pd.DataFrame(_log_rows[::-1]), use_container_width=True, hide_index=True)
    else:
        st.info("ยังไม่มีข้อมูล weekly return — รัน weekly job ก่อน")

    # Weights comparison: V3 (rule-based today) vs ML-blend today
    if _pb_rows and _pb_rows[-1].get("blend_weights"):
        with st.expander("Weights Comparison: A vs B (สัปดาห์นี้)", expanded=False):
            _bw = _pb_rows[-1]["blend_weights"]
            # Load current rule-based weights from regime probs
            try:
                from flowmacro.data.store import read_series as _rs
                from flowmacro.portfolio.allocator import compute_blended_weights as _cbw
                from flowmacro.data.store import read_series
                import datetime as _dt_mod
                _probs_raw: dict[str, float] = {}
                for _rk, _sid in [
                    ("GOLDILOCKS",  "regime_prob_goldilocks"),
                    ("REFLATION",   "regime_prob_reflation"),
                    ("STAGFLATION", "regime_prob_stagflation"),
                    ("DEFLATION",   "regime_prob_deflation"),
                ]:
                    _s = read_series(_sid, start=str(_dt_mod.date.today() - _dt_mod.timedelta(days=8)))
                    if not _s.empty:
                        _probs_raw[_rk] = float(_s.dropna().iloc[-1])
                _rb_weights = _cbw(_probs_raw) if len(_probs_raw) == 4 else {}
            except Exception:
                _rb_weights = {}

            _all_assets = sorted(set(list(_bw.keys()) + list(_rb_weights.keys())))
            _wt_rows = []
            for _asset in _all_assets:
                _wa = _rb_weights.get(_asset, 0.0)
                _wb = _bw.get(_asset, 0.0)
                _diff = _wb - _wa
                if _wa < 0.001 and _wb < 0.001:
                    continue
                _wt_rows.append({
                    "Asset":     _asset,
                    "A (Rule)":  f"{_wa * 100:.1f}%",
                    "B (ML)":    f"{_wb * 100:.1f}%",
                    "Diff":      f"{_diff * 100:+.1f}pp",
                })
            st.dataframe(pd.DataFrame(_wt_rows), use_container_width=True, hide_index=True)
            st.caption("ML-blend ปรับ weights ตาม XGBoost probs 30% — สัปดาห์นี้ ML=REFLATION vs Rule=TRANSITIONING")
