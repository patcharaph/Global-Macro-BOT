from datetime import date, datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="FlowMacro", layout="wide", page_icon="📈")

_REGIME_ICON = {
    "GOLDILOCKS":    "🟢",
    "REFLATION":     "🟡",
    "STAGFLATION":   "🔴",
    "DEFLATION":     "🔵",
    "TRANSITIONING": "⚪",
}
_REGIME_COLOR = {
    "GOLDILOCKS":    "#2ecc71",
    "REFLATION":     "#f1c40f",
    "STAGFLATION":   "#e74c3c",
    "DEFLATION":     "#3498db",
    "TRANSITIONING": "#95a5a6",
}
_REGIME_DESC = {
    "GOLDILOCKS":    "Growth ↑  Inflation ↓ — risk-on: equities, EM, small cap",
    "REFLATION":     "Growth ↑  Inflation ↑ — commodities, EM, value stocks",
    "STAGFLATION":   "Growth ↓  Inflation ↑ — gold, commodities, cash",
    "DEFLATION":     "Growth ↓  Inflation ↓ — long bonds, USD, cash",
    "TRANSITIONING": "Signals unclear — high uncertainty, stay defensive",
}
_REGIME_DECODE = {1: "GOLDILOCKS", 2: "REFLATION", 3: "STAGFLATION", 4: "DEFLATION", 0: "TRANSITIONING"}


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=300)
def load_latest_regime() -> dict | None:
    try:
        db = _db()
        def _latest(sid: str):
            r = db.table("raw_series").select("date,value").eq("series_id", sid).order("date", desc=True).limit(1).execute()
            return (r.data[0]["value"], r.data[0]["date"]) if r.data else (None, None)
        code, run_date   = _latest("regime_code")
        conf, _          = _latest("regime_confidence")
        growth, _        = _latest("growth_score")
        inflation, _     = _latest("inflation_score")
        if code is None:
            return None
        return {
            "regime":          _REGIME_DECODE.get(int(code), "UNKNOWN"),
            "confidence":      conf,
            "growth_score":    growth,
            "inflation_score": inflation,
            "run_date":        run_date,
        }
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_backtest_summary() -> dict | None:
    try:
        r = _db().table("backtest_runs").select("*").order("run_date", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_staleness() -> pd.DataFrame:
    try:
        from flowmacro.regime.indicators import INDICATORS, stale_threshold
        db = _db()
        today = date.today()
        rows = []
        series_ids = list(dict.fromkeys(
            [i.series_id for i in INDICATORS] + [
                "copper_gold", "spy_200ma", "dxy_trend", "cpi_yoy",
                "regime_code", "regime_confidence",
            ]
        ))
        for sid in series_ids:
            r = db.table("raw_series").select("date").eq("series_id", sid) \
                  .order("date", desc=True).limit(1).execute()
            if not r.data:
                continue
            last_date = pd.to_datetime(r.data[0]["date"]).date()
            stale = (today - last_date).days
            threshold = stale_threshold(sid)
            status = "✅ OK" if stale <= threshold else ("⚠️ Warn" if stale <= threshold * 2 else "🔴 Stale")
            rows.append({"Indicator": sid, "Last Update": str(last_date),
                         "Days Stale": stale, "Status": status})
        return pd.DataFrame(rows).sort_values("Days Stale", ascending=False)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_thb_rate() -> float | None:
    try:
        fx = yf.download("THB=X", period="2d", progress=False, auto_adjust=True)
        return float(fx["Close"].iloc[-1]) if not fx.empty else None
    except Exception:
        return None


def _quadrant_chart(growth: float, inflation: float, regime: str) -> go.Figure:
    color = _REGIME_COLOR.get(regime, "#95a5a6")
    fig = go.Figure()

    quads = [
        (0, 50, 50, 100, "rgba(52,152,219,0.15)"),
        (50, 50, 100, 100, "rgba(46,204,113,0.15)"),
        (0, 0, 50, 50, "rgba(231,76,60,0.15)"),
        (50, 0, 100, 50, "rgba(241,196,15,0.15)"),
    ]
    for x0, y0, x1, y1, fill in quads:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=fill, line_width=0, layer="below")

    for x, y, text in [
        (25, 75, "🔵 DEFLATION"), (75, 75, "🟢 GOLDILOCKS"),
        (25, 25, "🔴 STAGFLATION"), (75, 25, "🟡 REFLATION"),
    ]:
        fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                           font=dict(size=11, color="rgba(255,255,255,0.55)"),
                           xanchor="center", yanchor="middle")

    fig.add_shape(type="line", x0=50, y0=0, x1=50, y1=100,
                  line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot"))
    fig.add_shape(type="line", x0=0, y0=50, x1=100, y1=50,
                  line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot"))

    fig.add_trace(go.Scatter(
        x=[growth], y=[inflation],
        mode="markers+text",
        text=["NOW"],
        textposition="top center",
        textfont=dict(size=10, color="white"),
        marker=dict(size=18, color=color, line=dict(width=2, color="white")),
        hovertemplate=f"Growth: {growth:.1f}<br>Inflation: {inflation:.1f}<extra></extra>",
        showlegend=False,
    ))

    fig.update_layout(
        xaxis=dict(range=[0, 100], title="Growth Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100], color="rgba(255,255,255,0.5)"),
        yaxis=dict(range=[0, 100], title="Inflation Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100], color="rgba(255,255,255,0.5)"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=50, r=10, t=10, b=50),
    )
    return fig


# ── Header ───────────────────────────────────────────────────────────────────
st.title("📈 FlowMacro — Macro Regime Dashboard")
st.caption(f"Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── Regime ───────────────────────────────────────────────────────────────────
latest = load_latest_regime()

if latest:
    regime          = latest["regime"]
    confidence      = float(latest["confidence"])
    growth_score    = float(latest["growth_score"])
    inflation_score = float(latest["inflation_score"])
    run_date        = latest["run_date"]
else:
    regime = confidence = growth_score = inflation_score = run_date = None

icon  = _REGIME_ICON.get(regime or "", "❓")
label = regime or "NO DATA — Run weekly job first"
st.subheader(f"{icon}  **{label}**  (as of {run_date or '—'})")
if regime:
    st.caption(_REGIME_DESC.get(regime, ""))

thb_rate = load_thb_rate()

col_metrics, col_chart = st.columns([1, 1])

with col_metrics:
    c1, c2 = st.columns(2)
    c1.metric("Confidence",      f"{confidence:.1f}%"     if confidence      is not None else "—")
    c2.metric("THB/USD",         f"{thb_rate:.2f}"         if thb_rate        is not None else "—")
    c3, c4 = st.columns(2)
    c3.metric("Growth Score",    f"{growth_score:.1f}"    if growth_score    is not None else "—")
    c4.metric("Inflation Score", f"{inflation_score:.1f}" if inflation_score is not None else "—")

    st.divider()

    with st.expander("Data Staleness", expanded=False):
        staleness = load_staleness()
        if staleness.empty:
            st.info("No data yet — run the daily job first.")
        else:
            st.dataframe(staleness, use_container_width=True, hide_index=True)

with col_chart:
    if growth_score is not None and inflation_score is not None:
        st.plotly_chart(
            _quadrant_chart(growth_score, inflation_score, regime or ""),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    else:
        st.info("Run weekly job to populate regime scores.")

st.divider()

# ── Backtest Summary ──────────────────────────────────────────────────────────
st.subheader("Backtest: FlowMacro vs 60/40")
bt = load_backtest_summary()
if bt is None:
    st.info("No backtest results — run `python scripts/run_backtest.py`")
else:
    p_start = bt.get("period_start") or "—"
    p_end   = bt.get("period_end")   or "—"
    st.caption(f"Run: {bt.get('run_date','—')}  |  Period: {p_start} → {p_end}")

    b1, b2, b3 = st.columns(3)
    sharpe  = bt.get("sharpe_ratio")
    b_sharpe = bt.get("benchmark_sharpe")
    ret     = bt.get("annual_return")
    b_ret   = bt.get("benchmark_return")

    dd = bt.get("max_drawdown")

    b1.metric("Sharpe Ratio",  f"{sharpe:.2f}"  if sharpe is not None else "—",
              delta=f"60/40: {b_sharpe:.2f}" if b_sharpe is not None else None)
    b2.metric("Max Drawdown",  f"{dd:.1f}%"     if dd     is not None else "—",
              delta_color="inverse")
    b3.metric("Total Return",  f"{ret:.1f}%"    if ret    is not None else "—",
              delta=f"60/40: {b_ret:.1f}%" if b_ret is not None else None)

    if bt.get("outperforms_benchmark") is False:
        st.warning("FlowMacro underperforms 60/40 — confidence threshold may need tuning")

st.divider()
st.caption("FlowMacro — personal use only, not investment advice")
