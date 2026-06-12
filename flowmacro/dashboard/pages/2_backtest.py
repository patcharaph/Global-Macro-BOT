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
                delta="Agrees" if _latest["agrees"] else "Disagrees",
                delta_color="normal" if _latest["agrees"] else "inverse")

    # ─ Agreement timeline chart ────────────────────────────────────────────────
    _dates  = [pd.to_datetime(r["run_date"]) for r in _rows]
    _agree  = [r["agrees"] for r in _rows]
    _ml_reg = [r["ml_regime"] for r in _rows]
    _rb_reg = [r["rb_regime"] for r in _rows]
    _ml_con = [r.get("ml_confidence", 0) for r in _rows]

    fig_ml = go.Figure()

    # ML predictions — top row (y=1.5)
    fig_ml.add_trace(go.Scatter(
        x=_dates, y=[1.5] * len(_dates),
        mode="markers+text",
        marker=dict(
            size=20,
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
            size=20,
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
        xaxis=dict(showgrid=False, tickformat="%b %d", color="rgba(0,212,255,0.6)"),
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
