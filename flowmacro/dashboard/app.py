from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import pathlib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from supabase import create_client
from flowmacro.config import settings
from flowmacro.portfolio.allocator import REGIME_WEIGHTS, compute_blended_weights

st.set_page_config(page_title="FlowMacro", layout="wide", initial_sidebar_state="collapsed")

# ── Constants ─────────────────────────────────────────────────
_REGIME_COLOR = {
    "GOLDILOCKS":    "#00ff88",
    "REFLATION":     "#ffcc00",
    "STAGFLATION":   "#ff4466",
    "DEFLATION":     "#00d4ff",
    "TRANSITIONING": "#8888aa",
}
_REGIME_DESC = {
    "GOLDILOCKS":    "Growth ↑  Inflation ↓ — risk-on: equities, EM, small cap",
    "REFLATION":     "Growth ↑  Inflation ↑ — commodities, EM, value stocks",
    "STAGFLATION":   "Growth ↓  Inflation ↑ — gold, commodities, cash",
    "DEFLATION":     "Growth ↓  Inflation ↓ — long bonds, USD, cash",
    "TRANSITIONING": "Signals unclear — high uncertainty, stay defensive",
}
_REGIME_DECODE = {1: "GOLDILOCKS", 2: "REFLATION", 3: "STAGFLATION", 4: "DEFLATION", 0: "TRANSITIONING"}

_ASSET_COLOR = {
    "SPY": "#00ff88", "QQQ": "#00cc66", "IWM": "#009944", "EFA": "#44ffaa", "EEM": "#88ffcc",
    "BTC-USD": "#bf5fff",
    "TLT": "#00d4ff", "IEF": "#0099cc", "SHY": "#006699",
    "GLD": "#ffcc00", "SLV": "#ffaa44", "DBC": "#ff8800", "UUP": "#ff6600",
    "Cash": "#1e2d45",
}
_REGIME_NEON = {
    "GOLDILOCKS": "#00ff88", "REFLATION": "#ffcc00",
    "STAGFLATION": "#ff4466", "DEFLATION": "#00d4ff",
}
_PIE_COLORS = [
    "#00ff88", "#00d4ff", "#ffcc00", "#ff4466", "#bf5fff",
    "#ff8800", "#00ffcc", "#ff66aa", "#88ff00", "#4488ff", "#ffaa00", "#aa44ff",
]


# ── DB ────────────────────────────────────────────────────────
def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


# ── Data loading ──────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_regime_probabilities() -> dict[str, float] | None:
    try:
        db = _db()
        probs: dict[str, float] = {}
        for regime, series_id in [
            ("GOLDILOCKS",  "regime_prob_goldilocks"),
            ("REFLATION",   "regime_prob_reflation"),
            ("STAGFLATION", "regime_prob_stagflation"),
            ("DEFLATION",   "regime_prob_deflation"),
        ]:
            r = (db.table("raw_series")
                   .select("value")
                   .eq("series_id", series_id)
                   .order("date", desc=True)
                   .limit(1)
                   .execute())
            if r.data:
                probs[regime] = float(r.data[0]["value"])
        if len(probs) == 4:
            return probs
    except Exception:
        pass
    try:
        from flowmacro.regime.probabilities import compute_regime_probabilities
        latest = load_latest_regime()
        if latest and latest.get("growth_score") is not None and latest.get("inflation_score") is not None:
            return compute_regime_probabilities(
                float(latest["growth_score"]),
                float(latest["inflation_score"]),
            )
    except Exception:
        pass
    return None


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


@st.cache_data(ttl=300)
def load_latest_thesis() -> dict | None:
    try:
        r = _db().table("thesis_runs").select("*").order("created_at", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_cot_series() -> dict[str, pd.Series]:
    from flowmacro.data.store import read_series
    start = str((date.today() - timedelta(weeks=52)))
    result = {}
    labels = {
        "cot_sp500_net":       "S&P 500",
        "cot_treasury10y_net": "10Y Treasury",
        "cot_gold_net":        "Gold",
        "cot_crude_net":       "Crude Oil",
    }
    for sid, label in labels.items():
        try:
            s = read_series(sid, start=start)
            if not s.empty:
                result[label] = s
        except Exception:
            pass
    return result


@st.cache_data(ttl=3600)
def load_thb_rate() -> float | None:
    try:
        fx = yf.download("THB=X", period="5d", progress=False, auto_adjust=True)
        if fx.empty:
            return None
        return float(fx["Close"].squeeze().dropna().iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_vix() -> float | None:
    try:
        vix = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if vix.empty:
            return None
        return float(vix["Close"].squeeze().dropna().iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_paper_portfolio() -> dict | None:
    try:
        from flowmacro.data.store import read_series
        s = read_series("paper_total_value", start="2020-01-01")
        if s.empty:
            return None
        current   = float(s.dropna().iloc[-1])
        last_date = s.last_valid_index().date()
        pnl_pct   = (current / 3_000.0 - 1) * 100
        return {"value_usd": current, "pnl_pct": pnl_pct, "as_of": str(last_date)}
    except Exception:
        return None


@st.cache_data(ttl=86400)
def load_backtest_oos() -> pd.Series:
    try:
        here = pathlib.Path(__file__).resolve()
        root = here.parent.parent.parent
        path = root / "scripts" / "backtest_v3.csv"
        df = pd.read_csv(str(path), parse_dates=["Date"]).set_index("Date")
        return df["oos_v3"].dropna()
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=3600)
def load_ticker_prices_rv(ticker: str, start: str) -> pd.Series:
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        return df["Close"].squeeze().dropna()
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=300)
def load_portfolio_b_live() -> dict | None:
    try:
        from flowmacro.data.store import read_paper_portfolio_ml
        df = read_paper_portfolio_ml()
        if df.empty:
            return None
        latest_val = float(df["portfolio_value"].iloc[-1])
        pnl_pct    = (latest_val / 3_000.0 - 1) * 100
        return {"value_usd": latest_val, "pnl_pct": pnl_pct, "n_weeks": len(df)}
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_regime_history(weeks: int = 52) -> pd.DataFrame:
    try:
        start = str((date.today() - timedelta(weeks=weeks)).isoformat())
        r = _db().table("regime_history").select("run_date,regime").gte("run_date", start).order("run_date").execute()
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        df["run_date"] = pd.to_datetime(df["run_date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_v2_bundle() -> dict:
    try:
        import json
        data = _db().storage.from_("flowmacro-models").download("xgb_regime_v2_meta.json")
        meta = json.loads(data)
        return {
            "ok":          True,
            "wf_accuracy": meta.get("wf_accuracy"),
            "nber_passed": meta.get("nber_passed"),
            "nber_total":  meta.get("nber_total", 6),
            "n_features":  meta.get("n_features"),
            "pruned":      meta.get("pruned", []),
            "trained_at":  meta.get("trained_at", ""),
        }
    except Exception:
        return {"ok": False}


def load_ml_shadow() -> dict:
    try:
        rows = (
            _db().table("regime_history_ml")
            .select("run_date,ml_regime,ml_confidence,rb_regime,agrees")
            .order("run_date", desc=True).limit(26)
            .execute().data
        )
        if not rows:
            return {"active": True, "n_weeks": 0, "rows": []}
        n = len(rows)
        return {
            "active":         True,
            "n_weeks":        n,
            "latest":         rows[0],
            "agreement_rate": sum(1 for x in rows if x["agrees"]) / n * 100,
            "rows":           rows,
        }
    except Exception:
        return {"active": False, "n_weeks": 0, "rows": []}


# ── Helpers ───────────────────────────────────────────────────
def _days_to_next_friday() -> int:
    today = datetime.now(ZoneInfo("Asia/Bangkok")).date()
    days_ahead = 4 - today.weekday()
    if days_ahead == 0:
        return 0
    return days_ahead if days_ahead > 0 else days_ahead + 7


def _fmt_ret(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'+'if v >= 0 else ''}{v:.1f}%"


def _series_ret(series: pd.Series, start: str) -> float | None:
    if series.empty:
        return None
    sub = series[series.index >= pd.Timestamp(start)].dropna()
    if len(sub) < 2:
        return None
    return (float(sub.iloc[-1]) / float(sub.iloc[0]) - 1) * 100


def _ret_6040(spy: pd.Series, agg: pd.Series, start: str) -> float | None:
    s = pd.Timestamp(start)
    spy_s = spy[spy.index >= s].dropna()
    agg_s = agg[agg.index >= s].dropna()
    if len(spy_s) < 2 or len(agg_s) < 2:
        return None
    return 0.60 * (float(spy_s.iloc[-1] / spy_s.iloc[0]) - 1) * 100 + \
           0.40 * (float(agg_s.iloc[-1] / agg_s.iloc[0]) - 1) * 100


# ── Chart helpers ─────────────────────────────────────────────
def _prob_bars_chart(probs: dict[str, float]) -> go.Figure:
    sorted_items = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    labels = [r for r, _ in sorted_items]
    values = [v * 100 for _, v in sorted_items]
    colors = [_REGIME_COLOR[r] for r in labels]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
        text=[f"{v:.1f}%" for v in values],
        textposition="inside",
        textfont=dict(color="#000000", size=11, family="monospace"),
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 100], showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, color="#6b7a99",
                   tickfont=dict(family="monospace", size=11), autorange="reversed"),
        height=155,
        margin=dict(l=105, r=10, t=5, b=5),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _quadrant_chart(growth: float, inflation: float, regime: str) -> go.Figure:
    color = _REGIME_COLOR.get(regime, "#95a5a6")
    fig = go.Figure()
    quads = [
        (0,  50, 50, 100, "rgba(255,68,102,0.07)"),
        (50, 50, 100, 100, "rgba(255,204,0,0.07)"),
        (0,  0,  50,  50, "rgba(0,212,255,0.07)"),
        (50, 0,  100, 50, "rgba(0,255,136,0.07)"),
    ]
    for x0, y0, x1, y1, fill in quads:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=fill, line_width=0, layer="below")
    for x, y, text in [
        (25, 75, "STAGFLATION"), (75, 75, "REFLATION"),
        (25, 25, "DEFLATION"),   (75, 25, "GOLDILOCKS"),
    ]:
        quad_color = {"DEFLATION": "#00d4ff", "GOLDILOCKS": "#00ff88",
                      "STAGFLATION": "#ff4466", "REFLATION": "#ffcc00"}[text]
        fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                           font=dict(size=9, color=quad_color, family="monospace"),
                           xanchor="center", yanchor="middle", opacity=0.5)
    fig.add_shape(type="line", x0=50, y0=0, x1=50, y1=100,
                  line=dict(color="rgba(100,120,160,0.3)", width=1, dash="dot"))
    fig.add_shape(type="line", x0=0, y0=50, x1=100, y1=50,
                  line=dict(color="rgba(100,120,160,0.3)", width=1, dash="dot"))
    fig.add_trace(go.Scatter(
        x=[growth], y=[inflation],
        mode="markers+text",
        text=["NOW"],
        textposition="top center",
        textfont=dict(size=9, color=color, family="monospace"),
        marker=dict(size=16, color=color, line=dict(width=2, color="white"), symbol="circle"),
        hovertemplate=f"Growth: {growth:.1f}<br>Inflation: {inflation:.1f}<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 100], title="Growth Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100], color="#6b7a99",
                   title_font=dict(color="#6b7a99", size=10)),
        yaxis=dict(range=[0, 100], title="Inflation Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100], color="#6b7a99",
                   title_font=dict(color="#6b7a99", size=10)),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        height=270,
        margin=dict(l=50, r=10, t=10, b=46),
    )
    return fig


def _regime_timeline_chart(rb_df: pd.DataFrame, ml_rows: list) -> go.Figure:
    fig = go.Figure()

    def _add_band(pairs, y0, y1, row_label, x_anchor):
        if not pairs:
            return
        segments = []
        cur_r, seg_start = None, None
        for dt, regime in pairs:
            if regime != cur_r:
                if cur_r is not None:
                    segments.append((seg_start, dt, cur_r))
                cur_r, seg_start = regime, dt
        if cur_r:
            segments.append((seg_start, pairs[-1][0] + pd.Timedelta(weeks=1), cur_r))
        for start, end, regime in segments:
            clr = _REGIME_COLOR.get(regime, "#888888")
            fig.add_shape(type="rect", x0=start, x1=end, y0=y0, y1=y1,
                          fillcolor=clr, opacity=0.75, line_width=0, layer="below")
            if (end - start).days / 7 >= 5:
                fig.add_annotation(
                    x=start + (end - start) / 2, y=(y0 + y1) / 2,
                    text=regime[:4], showarrow=False,
                    font=dict(size=8, color="rgba(0,0,0,0.8)", family="monospace"),
                    xanchor="center", yanchor="middle",
                )
        fig.add_annotation(x=x_anchor, y=(y0 + y1) / 2, text=row_label,
                           showarrow=False, xref="paper",
                           font=dict(size=9, color="#6b7a99", family="monospace"),
                           xanchor="right", yanchor="middle", xshift=-6)

    if rb_df.empty:
        return fig
    rb_pairs = list(zip(rb_df["run_date"], rb_df["regime"]))
    _add_band(rb_pairs, 0.55, 1.0, "Rule", 0)
    if ml_rows:
        ml_pairs = sorted(
            [(pd.to_datetime(r["run_date"]), r["ml_regime"]) for r in ml_rows],
            key=lambda x: x[0],
        )
        _add_band(ml_pairs, 0.0, 0.45, "ML", 0)
    else:
        fig.add_annotation(x=0.5, y=0.22, text="ML accumulating...",
                           showarrow=False, xref="paper", yref="y",
                           font=dict(size=9, color="rgba(255,255,255,0.2)"),
                           xanchor="center", yanchor="middle")
    fig.add_vline(x=pd.Timestamp(date.today()),
                  line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dash"))
    x_min = min(rb_df["run_date"].min(), pd.Timestamp(date.today()) - pd.Timedelta(weeks=52))
    x_max = pd.Timestamp(date.today()) + pd.Timedelta(weeks=2)
    fig.update_layout(
        xaxis=dict(range=[x_min, x_max], showgrid=False, type="date",
                   tickformat="%b '%y", color="#6b7a99"),
        yaxis=dict(range=[-0.15, 1.15], showticklabels=False, showgrid=False),
        height=125, margin=dict(l=45, r=10, t=5, b=32),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


# ════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════

st.markdown("""<style>
.stApp { background-color: #0a0e1a !important; }
.block-container {
    padding-top: 0.6rem !important;
    padding-bottom: 2rem !important;
    max-width: 1400px !important;
}
[data-testid="metric-container"] {
    background: #0f1522 !important;
    border: 1px solid #1e2d45 !important;
    border-radius: 8px !important;
    padding: 12px 16px !important;
}
[data-testid="metric-container"] label {
    color: #6b7a99 !important;
    font-size: 0.68rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    font-family: monospace !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.25rem !important;
    font-family: monospace !important;
    color: #e8eaf0 !important;
}
[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-family: monospace !important;
    font-size: 0.78rem !important;
}
button[data-testid="stTab"] {
    font-family: monospace !important;
    font-size: 0.85rem !important;
    color: #6b7a99 !important;
}
button[data-testid="stTab"][aria-selected="true"] {
    color: #c9a84c !important;
    border-bottom-color: #c9a84c !important;
}
[data-testid="stDataFrame"] th {
    background: #080c14 !important;
    color: #6b7a99 !important;
    font-family: monospace !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.04em !important;
}
[data-testid="stDataFrame"] td {
    font-family: monospace !important;
    font-size: 0.86rem !important;
}
hr { border-color: #1e2d45 !important; }
h1, h2, h3, h4 { color: #e8eaf0 !important; font-family: monospace !important; }
.stAlert { border-radius: 8px !important; }
</style>""", unsafe_allow_html=True)

# ── Load all data ─────────────────────────────────────────────
latest        = load_latest_regime()
regime_probs  = load_regime_probabilities()
vix           = load_vix()
days_fri      = _days_to_next_friday()
thesis        = load_latest_thesis()
thb_rate      = load_thb_rate()
paper         = load_paper_portfolio()
_oos_rv       = load_backtest_oos()
_spy_rv       = load_ticker_prices_rv("SPY", start="2021-01-01")
_agg_rv       = load_ticker_prices_rv("AGG", start="2021-01-01")
_hist_df      = load_regime_history(weeks=52)
_ml_shad      = load_ml_shadow()
_v2           = load_v2_bundle()
_V1_BASELINE  = 0.663

if latest:
    regime          = latest["regime"]
    confidence      = float(latest["confidence"])
    growth_score    = float(latest["growth_score"])
    inflation_score = float(latest["inflation_score"])
    run_date        = latest["run_date"]
else:
    regime = confidence = growth_score = inflation_score = run_date = None

if regime_probs:
    dominant_regime = max(regime_probs, key=lambda r: regime_probs[r])
    dominant_prob   = regime_probs[dominant_regime]
else:
    dominant_regime = regime
    dominant_prob   = None

display_regime = dominant_regime or regime

# Blended allocation
_blend: dict[str, float] | None = None
if regime_probs:
    try:
        _raw_blend = compute_blended_weights(regime_probs)
        _blend = {k: v for k, v in _raw_blend.items() if v > 0.001}
        _blend["Cash"] = _blend.get("Cash", 0.0) + 0.20
    except Exception:
        pass

# Signal strength
if dominant_prob is not None:
    _strength_pct = max(0.0, (dominant_prob - 0.25) / 0.75) * 100
    if _strength_pct < 20:
        _sig_label, _sig_color = "WEAK", "#e74c3c"
    elif _strength_pct < 50:
        _sig_label, _sig_color = "MODERATE", "#f1c40f"
    else:
        _sig_label, _sig_color = "STRONG", "#2ecc71"
else:
    _strength_pct, _sig_label, _sig_color = 0, "NO DATA", "#444"

_conviction = thesis.get("conviction") if thesis else None
_is_weak    = _sig_label == "WEAK" or (_conviction is not None and _conviction <= 3)

# Action
if _is_weak:
    _action_text, _action_color = "HOLD  ·  WEAK SIGNAL", "#e74c3c"
    _action_desc = "สัญญาณอ่อน รอสัปดาห์หน้า"
elif days_fri == 0:
    _action_text, _action_color = "REBALANCE TODAY", "#c9a84c"
    _action_desc = "ดู Current Allocation"
else:
    _action_text, _action_color = f"HOLD  ·  {days_fri}d", "#2ecc71"
    _action_desc = f"Next rebalance in {days_fri} day{'s' if days_fri != 1 else ''}"

# VIX display
_vix_str   = f"{vix:.1f}" if vix is not None else "—"
_vix_label = ("LOW" if vix < 15 else "NORMAL" if vix < 20 else "ELEVATED" if vix < 30 else "HIGH") if vix else "—"
_vix_color = ("#2ecc71" if vix < 15 else "#f1c40f" if vix < 25 else "#e74c3c") if vix else "#444"

_conf_str   = f"{dominant_prob:.0%}" if dominant_prob is not None else "—"
_conf_color = ("#2ecc71" if dominant_prob >= 0.6 else "#f1c40f" if dominant_prob >= 0.4 else "#e74c3c") if dominant_prob else "#444"
_neon_r     = _REGIME_COLOR.get(display_regime or "", "#888")
_now_str    = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M")

# ── STATUS BAR ────────────────────────────────────────────────
st.markdown(
    f"<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:10px;"
    f"padding:11px 24px;margin-bottom:16px;display:flex;align-items:center;"
    f"font-family:monospace;font-size:0.88rem'>"
    f"<span style='color:{_neon_r};font-weight:bold;font-size:1rem'>"
    f"{display_regime or 'NO DATA'}</span>"
    f"<span style='color:#1e2d45;margin:0 20px;font-size:1.1rem'>│</span>"
    f"<span style='color:{_action_color};font-weight:bold'>{_action_text}</span>"
    f"<span style='color:#1e2d45;margin:0 20px;font-size:1.1rem'>│</span>"
    f"<span style='color:#6b7a99'>VIX&nbsp;</span>"
    f"<span style='color:{_vix_color}'>{_vix_str}"
    f"&nbsp;<span style='font-size:0.75rem'>[{_vix_label}]</span></span>"
    f"<span style='color:#1e2d45;margin:0 20px;font-size:1.1rem'>│</span>"
    f"<span style='color:#6b7a99'>Confidence&nbsp;</span>"
    f"<span style='color:{_conf_color};font-weight:bold'>{_conf_str}</span>"
    f"<span style='color:{_sig_color};font-size:0.75rem;margin-left:6px'>[{_sig_label}]</span>"
    f"<div style='flex:1'></div>"
    f"<span style='color:#2a3555;font-size:0.75rem'>{_now_str} BKK</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 3-COLUMN MAIN ─────────────────────────────────────────────
col_l, col_m, col_r = st.columns([1, 1.1, 0.95], gap="medium")

# ─ LEFT: Action + Allocation ─────────────────────────────────
with col_l:
    _conv_line = f"Conviction {_conviction}/10  ·  {thesis.get('run_date','')}" if _conviction else ""
    _conv_div  = (f'<div style="font-size:0.72rem;color:#3a4060;margin-top:8px">{_conv_line}</div>'
                  if _conv_line else "")
    st.markdown(
        f"<div style='background:#0f1522;border:1.5px solid {_action_color};"
        f"border-radius:10px;padding:16px 18px;margin-bottom:14px;"
        f"font-family:monospace;text-align:center'>"
        f"<div style='font-size:0.62rem;color:#6b7a99;text-transform:uppercase;"
        f"letter-spacing:1px;margin-bottom:8px'>This Week</div>"
        f"<div style='font-size:1.6rem;font-weight:bold;color:{_action_color}'>"
        f"{_action_text}</div>"
        f"<div style='font-size:0.8rem;color:#8895b3;margin-top:4px'>{_action_desc}</div>"
        f"{_conv_div}"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<p style='font-size:0.62rem;color:#6b7a99;text-transform:uppercase;"
        "letter-spacing:1px;font-family:monospace;margin-bottom:6px'>Current Allocation</p>",
        unsafe_allow_html=True,
    )

    if _blend:
        sorted_blend = sorted(_blend.items(), key=lambda x: x[1], reverse=True)
        assets = [a for a, _ in sorted_blend]
        pcts   = [w * 100 for _, w in sorted_blend]
        colors = [_ASSET_COLOR.get(a, "#2a3550") for a in assets]

        fig_alloc = go.Figure(go.Bar(
            x=pcts, y=assets, orientation="h",
            marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
            text=[f"{v:.0f}%" for v in pcts],
            textposition="inside",
            textfont=dict(color="#000", size=10, family="monospace"),
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        ))
        fig_alloc.update_layout(
            xaxis=dict(range=[0, max(pcts) * 1.12], showgrid=False, showticklabels=False),
            yaxis=dict(showgrid=False, color="#6b7a99",
                       tickfont=dict(family="monospace", size=10), autorange="reversed"),
            height=max(180, len(assets) * 27),
            margin=dict(l=70, r=5, t=4, b=4),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        st.plotly_chart(fig_alloc, use_container_width=True, config={"displayModeBar": False})

        _EQ  = {"SPY", "QQQ", "IWM", "EFA", "EEM", "BTC-USD"}
        _BD  = {"TLT", "IEF", "SHY"}
        _CMD = {"GLD", "SLV", "DBC", "UUP"}
        _eq_pct   = sum(v for k, v in _blend.items() if k in _EQ) * 100
        _bd_pct   = sum(v for k, v in _blend.items() if k in _BD) * 100
        _cm_pct   = sum(v for k, v in _blend.items() if k in _CMD) * 100
        _cash_pct = _blend.get("Cash", 0.0) * 100
        st.markdown(
            f"<div style='font-family:monospace;font-size:0.77rem;color:#6b7a99;"
            f"display:flex;gap:14px;flex-wrap:wrap;margin-top:2px'>"
            f"<span>Equity&nbsp;<b style='color:#2ecc71'>{_eq_pct:.0f}%</b></span>"
            f"<span>Bonds&nbsp;<b style='color:#00d4ff'>{_bd_pct:.0f}%</b></span>"
            f"<span>Cmdty&nbsp;<b style='color:#f1c40f'>{_cm_pct:.0f}%</b></span>"
            f"<span>Cash&nbsp;<b style='color:#3a4060'>{_cash_pct:.0f}%</b></span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Per-Regime Reference Weights", expanded=False):
            st.caption("แต่ละ regime ถือ 80% (20% cash) — reference เท่านั้น, portfolio จริงคือ blended ด้านบน")
            regime_order = ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]
            pie_cols = st.columns(4)
            for col, regime_name in zip(pie_cols, regime_order):
                weights  = REGIME_WEIGHTS.get(regime_name, {})
                labels   = list(weights.keys()) + ["Cash"]
                values   = [w * 100 for w in weights.values()] + [20.0]
                p_colors = [_PIE_COLORS[i % len(_PIE_COLORS)] for i in range(len(weights))] + ["#1e2d45"]
                fig_pie  = go.Figure(go.Pie(
                    labels=labels, values=values,
                    textinfo="label+percent", textposition="inside",
                    textfont=dict(size=9, family="monospace"),
                    marker=dict(colors=p_colors, line=dict(color="#080c1a", width=2)),
                    hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
                    sort=False, hole=0.25,
                ))
                fig_pie.update_layout(
                    title=dict(text=f"<b>{regime_name}</b>",
                               font=dict(size=11, color=_REGIME_NEON[regime_name], family="monospace"),
                               x=0.5, xanchor="center"),
                    showlegend=False, height=240,
                    margin=dict(l=5, r=5, t=32, b=5),
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                with col:
                    st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Run weekly job to populate regime scores.")

# ─ CENTER: Regime Intel ──────────────────────────────────────
with col_m:
    _badge_bg = _REGIME_COLOR.get(display_regime or "", "#888")
    st.markdown(
        f"<div style='margin-bottom:10px;font-family:monospace'>"
        f"<span style='background:{_badge_bg};color:#000;font-weight:bold;"
        f"font-size:0.9rem;padding:3px 14px;border-radius:5px'>"
        f"{display_regime or '—'}</span>"
        f"<span style='color:#2a3555;font-size:0.75rem;margin-left:10px'>{run_date or ''}</span>"
        f"</div>"
        f"<div style='font-size:0.8rem;color:#6b7a99;font-family:monospace;margin-bottom:12px'>"
        f"{_REGIME_DESC.get(display_regime or '', '')}</div>",
        unsafe_allow_html=True,
    )

    if growth_score is not None and inflation_score is not None:
        _gc = "#2ecc71" if growth_score > 50 else "#e74c3c"
        _ic = "#e74c3c" if inflation_score > 50 else "#2ecc71"
        _cg, _ci = st.columns(2)
        with _cg:
            st.markdown(
                f"<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:8px;"
                f"padding:10px 14px;text-align:center;font-family:monospace'>"
                f"<div style='font-size:0.6rem;color:#6b7a99;text-transform:uppercase;"
                f"letter-spacing:1px'>Growth</div>"
                f"<div style='font-size:1.85rem;font-weight:bold;color:{_gc}'>{growth_score:.0f}</div>"
                f"<div style='font-size:0.68rem;color:#3a4060'>"
                f"{'Expanding' if growth_score > 50 else 'Contracting'}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with _ci:
            st.markdown(
                f"<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:8px;"
                f"padding:10px 14px;text-align:center;font-family:monospace'>"
                f"<div style='font-size:0.6rem;color:#6b7a99;text-transform:uppercase;"
                f"letter-spacing:1px'>Inflation</div>"
                f"<div style='font-size:1.85rem;font-weight:bold;color:{_ic}'>{inflation_score:.0f}</div>"
                f"<div style='font-size:0.68rem;color:#3a4060'>"
                f"{'Above target' if inflation_score > 50 else 'Below target'}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        st.plotly_chart(
            _quadrant_chart(growth_score, inflation_score, display_regime or ""),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    else:
        st.info("Run weekly job to populate regime scores.")

    if regime_probs:
        st.markdown(
            "<p style='font-size:0.6rem;color:#6b7a99;text-transform:uppercase;"
            "letter-spacing:1px;font-family:monospace;margin-bottom:4px'>Regime Probabilities (V3)</p>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            _prob_bars_chart(regime_probs),
            use_container_width=True,
            config={"displayModeBar": False},
        )

# ─ RIGHT: Portfolio Performance ──────────────────────────────
with col_r:
    st.markdown(
        "<p style='font-size:0.62rem;color:#6b7a99;text-transform:uppercase;"
        "letter-spacing:1px;font-family:monospace;margin-bottom:8px'>Portfolio Performance</p>",
        unsafe_allow_html=True,
    )

    if paper:
        _thb_str   = f" / ฿{paper['value_usd'] * thb_rate:,.0f}" if thb_rate else ""
        _pnl_col   = "#2ecc71" if paper["pnl_pct"] >= 0 else "#e74c3c"
        _pnl_arrow = "▲" if paper["pnl_pct"] >= 0 else "▼"
        st.markdown(
            f"<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:10px;"
            f"padding:14px 16px;margin-bottom:12px'>"
            f"<div style='font-size:0.6rem;color:#6b7a99;font-family:monospace;"
            f"text-transform:uppercase;letter-spacing:1px'>Portfolio A · Since Jun 2026</div>"
            f"<div style='font-size:1.55rem;font-weight:bold;color:#e8eaf0;"
            f"font-family:monospace;margin:4px 0'>${paper['value_usd']:,.0f}{_thb_str}</div>"
            f"<div style='font-size:0.92rem;color:{_pnl_col};font-family:monospace'>"
            f"{_pnl_arrow} {paper['pnl_pct']:+.1f}%"
            f"<span style='font-size:0.7rem;color:#6b7a99'>&nbsp;vs $3,000 start</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:10px;"
            "padding:14px 16px;margin-bottom:12px;font-family:monospace;"
            "color:#3a4060;font-size:0.85rem'>Portfolio A — data after first Friday run</div>",
            unsafe_allow_html=True,
        )

    _live_weeks = (date.today() - date(2026, 6, 3)).days // 7
    _rv_periods = [
        ("YTD",  "2026-01-01"),
        ("1Y",   str(date.today() - timedelta(days=365))),
        ("3Y",   str(date.today() - timedelta(days=1095))),
        ("5Y",   str(date.today() - timedelta(days=1825))),
        (f"Live ({_live_weeks}w)", "2026-06-03"),
    ]

    _rv_rows = []
    for _pl, _ps in _rv_periods:
        if _pl.startswith("Live"):
            _fm  = paper["pnl_pct"] if paper else None
        else:
            _fm  = _series_ret(_oos_rv, _ps)
        _spy   = _series_ret(_spy_rv, _ps)
        _alpha = (_fm - _spy) if (_fm is not None and _spy is not None) else None
        _rv_rows.append({
            "Period":    _pl,
            "FlowMacro": _fmt_ret(_fm),
            "SPY":       _fmt_ret(_spy),
            "60/40":     _fmt_ret(_ret_6040(_spy_rv, _agg_rv, _ps)),
            "Alpha":     _fmt_ret(_alpha),
        })

    st.dataframe(pd.DataFrame(_rv_rows), use_container_width=True, hide_index=True)
    st.caption("FlowMacro YTD–5Y = backtest OOS  ·  Live = ผลจริง  ·  Benchmark = yfinance")

    _ppb = load_portfolio_b_live()
    if _ppb:
        _ppb_col = "#2ecc71" if _ppb["pnl_pct"] >= 0 else "#e74c3c"
        st.markdown(
            f"<div style='background:#0f1522;border:1px solid #1e2d45;border-radius:8px;"
            f"padding:10px 14px;margin-top:8px'>"
            f"<div style='font-size:0.6rem;color:#6b7a99;font-family:monospace;"
            f"text-transform:uppercase;letter-spacing:1px'>Portfolio B (ML-blend 30%)</div>"
            f"<div style='font-size:0.88rem;color:{_ppb_col};font-family:monospace;margin-top:4px'>"
            f"${_ppb['value_usd']:,.0f}  ·  {_ppb['pnl_pct']:+.1f}%  ·  {_ppb['n_weeks']}w</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

# ── TABS ──────────────────────────────────────────────────────
st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

tab_thesis, tab_cot, tab_hist, tab_ml, tab_dq = st.tabs([
    "AI Thesis", "COT Signals", "Regime History", "ML Dev", "Data Quality",
])

# ─ Tab: AI Thesis ────────────────────────────────────────────
with tab_thesis:
    t_hdr, t_btn = st.columns([3, 1])
    with t_hdr:
        if thesis:
            st.caption(
                f"Generated: {thesis.get('run_date','—')}  ·  "
                f"Regime: {thesis.get('regime','—')}  ·  Model: {thesis.get('model','—')}"
            )
        else:
            st.caption("No thesis yet — run weekly job or click Generate.")
    with t_btn:
        if st.button("Generate Thesis", type="secondary", disabled=(latest is None)):
            if latest:
                try:
                    from flowmacro.thesis.generator import generate_thesis, save_thesis
                    with st.spinner("Calling OpenRouter..."):
                        t = generate_thesis(
                            display_regime or latest["regime"],
                            dominant_prob * 100 if dominant_prob is not None else float(latest["confidence"]),
                            float(latest["growth_score"]),
                            float(latest["inflation_score"]),
                        )
                        save_thesis(t)
                    st.success(f"Thesis generated (conviction {t.conviction}/10)")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    if thesis:
        conv = thesis.get("conviction", 0)
        conv_color = "#2ecc71" if conv >= 7 else ("#f1c40f" if conv >= 4 else "#e74c3c")
        st.markdown(
            f"<span style='font-size:1.8rem;font-weight:bold;color:{conv_color};"
            f"font-family:monospace'>Conviction {conv}/10</span>",
            unsafe_allow_html=True,
        )
        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown("**คำแนะนำ**")
            st.info(thesis.get("recommendation", "—"))
            st.markdown("**เหตุผล**")
            st.write(thesis.get("reasoning", "—"))
        with tc2:
            st.markdown("**ความเสี่ยง**")
            st.warning(thesis.get("risks", "—"))

# ─ Tab: COT Signals ──────────────────────────────────────────
with tab_cot:
    st.caption(
        "COT (Commitments of Traders) — net position ของ Non-Commercial traders (hedge funds)  ·  "
        "**บวก** = net long  ·  **ลบ** = net short  ·  หน่วย: contracts"
    )
    cot_data = load_cot_series()
    if not cot_data:
        st.info("No COT data yet — run weekly job first.")
    else:
        _cot_colors = {
            "S&P 500": "#2ecc71", "10Y Treasury": "#3498db",
            "Gold": "#f1c40f", "Crude Oil": "#e67e22",
        }
        def _hex_rgba(h: str, a: float = 0.12) -> str:
            h = h.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{a})"

        cot_items = list(cot_data.items())
        for row_start in range(0, len(cot_items), 2):
            row_cols = st.columns(2)
            for col, (label, series) in zip(row_cols, cot_items[row_start:row_start + 2]):
                with col:
                    clr = _cot_colors.get(label, "#95a5a6")
                    last_val = series.iloc[-1] if not series.empty else 0
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=series.index, y=series.values,
                        mode="lines", line=dict(color=clr, width=2),
                        fill="tozeroy", fillcolor=_hex_rgba(clr),
                        hovertemplate="%{x|%Y-%m-%d}<br>Net: %{y:,.0f} contracts<extra></extra>",
                        showlegend=False,
                    ))
                    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.15)", width=1, dash="dot"))
                    fig.update_layout(
                        title=dict(
                            text=f"<b>{label}</b>  <span style='font-size:0.8em;color:#6b7a99'>{last_val:+,.0f} contracts</span>",
                            font=dict(size=12, color="#e8eaf0", family="monospace"),
                        ),
                        height=230, margin=dict(l=5, r=5, t=42, b=26),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=False, color="#6b7a99"),
                        yaxis=dict(showgrid=False, color="#6b7a99", tickformat=".2s"),
                    )
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ─ Tab: Regime History ───────────────────────────────────────
with tab_hist:
    if _hist_df.empty:
        st.info("No regime history — run weekly job first.")
    else:
        st.plotly_chart(
            _regime_timeline_chart(_hist_df, _ml_shad.get("rows", [])),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        _chips = " ".join(
            f"<span style='background:{_c};padding:2px 10px;border-radius:3px;"
            f"font-size:0.72rem;color:#000;font-family:monospace;margin-right:4px'>{_r[:4]}</span>"
            for _r, _c in list(_REGIME_COLOR.items())[:4]
        )
        st.markdown(_chips, unsafe_allow_html=True)

# ─ Tab: ML Dev ───────────────────────────────────────────────
with tab_ml:
    ml_l, ml_r = st.columns(2, gap="large")

    with ml_l:
        st.markdown("#### ML Shadow Mode")
        st.caption("XGBoost run ควบคู่ rule-based ทุกศุกร์ — ยังไม่กระทบ portfolio จนกว่าจะผ่าน graduation")

        if not _ml_shad.get("active"):
            st.warning("ML shadow unavailable — check regime_history_ml table.")
        elif _ml_shad["n_weeks"] == 0:
            st.info("Shadow mode active — predictions log every Friday. No data yet.")
        else:
            _n      = _ml_shad["n_weeks"]
            _rate   = _ml_shad["agreement_rate"]
            _latest = _ml_shad["latest"]
            _ml_r   = _latest["ml_regime"]
            _rb_r   = _latest["rb_regime"]
            _agrees = _latest["agrees"]
            _ml_c   = _latest.get("ml_confidence") or 0

            _ma, _mb, _mc = st.columns(3)

            with _ma:
                st.markdown("**Latest Prediction**")
                _ml_col = _REGIME_COLOR.get(_ml_r, "#888")
                _rb_col = _REGIME_COLOR.get(_rb_r, "#888")
                st.markdown(
                    f"ML:&nbsp;&nbsp;<span style='color:{_ml_col};font-weight:bold'>{_ml_r}</span>"
                    f"<span style='font-size:0.8rem;color:#6b7a99'>&nbsp;({_ml_c:.1f})</span><br>"
                    f"Rule: <span style='color:{_rb_col};font-weight:bold'>{_rb_r}</span>",
                    unsafe_allow_html=True,
                )
                _ag_col  = "#2ecc71" if _agrees else "#e74c3c"
                _ag_text = "Agrees" if _agrees else "Disagrees"
                st.markdown(
                    f"<span style='color:{_ag_col}'>{_ag_text}</span>"
                    f"<span style='color:#6b7a99;font-size:0.8rem'> — {_latest['run_date']}</span>",
                    unsafe_allow_html=True,
                )

            with _mb:
                _bar_col = "#2ecc71" if _rate >= 70 else ("#f1c40f" if _rate >= 50 else "#e74c3c")
                st.markdown(f"**Agreement ({_n}w)**")
                st.markdown(
                    f"<div style='background:#1a1a2e;border-radius:4px;height:8px;width:100%;margin-bottom:6px'>"
                    f"<div style='background:{_bar_col};height:100%;width:{min(_rate,100):.0f}%;border-radius:4px'></div></div>"
                    f"<span style='font-size:1.5rem;font-weight:bold;color:{_bar_col}'>{_rate:.0f}%</span>"
                    f"<span style='color:#6b7a99;font-size:0.78rem'> / 70% target</span>",
                    unsafe_allow_html=True,
                )

            with _mc:
                _weeks_left = max(0, 26 - _n)
                st.markdown("**Graduation**")
                _agree_sym  = "<span style='color:#2ecc71'>OK</span>" if _rate >= 70 \
                              else f"<span style='color:#f1c40f'>{_rate:.0f}%</span>"
                _period_sym = f"{_n}/26 weeks" if _weeks_left > 0 \
                              else "<span style='color:#2ecc71'>Complete</span>"
                st.markdown(
                    f"Agreement: {_agree_sym}<br>"
                    f"NBER 5/6: <span style='color:#2ecc71'>OK</span><br>"
                    f"Live: {_period_sym}",
                    unsafe_allow_html=True,
                )

    with ml_r:
        st.markdown("#### XGBoost v2 Development")
        st.caption("31 features (17 เดิม + 14 leading) — shadow mode, targeting Dec 2026")

        if not _v2["ok"]:
            st.info("v2 bundle not found — run scripts/train_regime_xgb_v2.py first.")
        else:
            _wf         = _v2["wf_accuracy"]
            _nber       = _v2["nber_passed"]
            _nber_total = _v2.get("nber_total", 6)
            _nfeat      = _v2["n_features"]
            _ratio      = round(712 / _nfeat, 1) if _nfeat else 0

            _acc_ok       = isinstance(_wf, float) and _wf > _V1_BASELINE
            _nber_ok      = isinstance(_nber, int) and _nber == _nber_total and _nber_total >= 3
            _ratio_ok     = _ratio >= 20
            _criteria_met = sum([_acc_ok, _nber_ok, _ratio_ok])

            v2a, v2b, v2c, v2d = st.columns(4)

            with v2a:
                _wf_pct = f"{_wf:.1%}" if isinstance(_wf, float) else "—"
                _wf_col = "#2ecc71" if _acc_ok else ("#f1c40f" if isinstance(_wf, float) and _wf > 0.60 else "#e74c3c")
                st.markdown(
                    f"<div style='font-size:0.62rem;color:#6b7a99'>Walk-forward Acc</div>"
                    f"<div style='font-size:1.6rem;font-weight:bold;color:{_wf_col}'>{_wf_pct}</div>"
                    f"<div style='font-size:0.68rem;color:#3a4060'>baseline {_V1_BASELINE:.1%}</div>",
                    unsafe_allow_html=True,
                )
            with v2b:
                _nber_str = f"{_nber}/{_nber_total}" if isinstance(_nber, int) else "—"
                _nber_col = "#2ecc71" if _nber_ok else "#e74c3c"
                st.markdown(
                    f"<div style='font-size:0.62rem;color:#6b7a99'>NBER Episodes</div>"
                    f"<div style='font-size:1.6rem;font-weight:bold;color:{_nber_col}'>{_nber_str}</div>"
                    f"<div style='font-size:0.68rem;color:#3a4060'>pre-2013 skipped</div>",
                    unsafe_allow_html=True,
                )
            with v2c:
                _ratio_col = "#2ecc71" if _ratio_ok else "#e74c3c"
                st.markdown(
                    f"<div style='font-size:0.62rem;color:#6b7a99'>Sample/Feature</div>"
                    f"<div style='font-size:1.6rem;font-weight:bold;color:{_ratio_col}'>{_ratio}:1</div>"
                    f"<div style='font-size:0.68rem;color:#3a4060'>need ≥20:1</div>",
                    unsafe_allow_html=True,
                )
            with v2d:
                _st_col  = "#2ecc71" if _criteria_met == 3 else ("#f1c40f" if _criteria_met >= 2 else "#e74c3c")
                _st_text = "Ready" if _criteria_met == 3 else f"{_criteria_met}/3 met"
                st.markdown(
                    f"<div style='font-size:0.62rem;color:#6b7a99'>Status</div>"
                    f"<div style='font-size:1.1rem;font-weight:bold;color:{_st_col}'>{_st_text}</div>"
                    f"<div style='font-size:0.68rem;color:#3a4060'>target Dec 2026</div>",
                    unsafe_allow_html=True,
                )

            _bar_w   = int(_criteria_met / 3 * 100)
            _bar_col = "#2ecc71" if _criteria_met == 3 else ("#f1c40f" if _criteria_met >= 2 else "#e74c3c")
            _missing = []
            if not _acc_ok:
                _missing.append(f"accuracy {_wf:.1%} < {_V1_BASELINE:.1%}" if isinstance(_wf, float) else "accuracy —")
            if not _nber_ok:
                _missing.append(f"NBER {_nber}/{_nber_total}" if isinstance(_nber, int) else "NBER —")
            if not _ratio_ok:
                _missing.append(f"ratio {_ratio}:1 < 20:1")
            _miss_str = "  ·  ".join(_missing) if _missing else "all criteria met ✓"
            st.markdown(
                f"<div style='background:#1a1a2e;border-radius:4px;height:6px;width:100%;margin:10px 0 4px'>"
                f"<div style='background:{_bar_col};height:100%;width:{_bar_w}%;border-radius:4px'></div></div>"
                f"<span style='font-size:0.72rem;color:#6b7a99'>{_miss_str}"
                f"  ·  retrained quarterly via GitHub Actions</span>",
                unsafe_allow_html=True,
            )

# ─ Tab: Data Quality ─────────────────────────────────────────
with tab_dq:
    _dq_data = load_staleness()
    if not _dq_data.empty:
        _ok       = int((_dq_data["Status"].str.startswith("✅")).sum())
        _total    = len(_dq_data)
        _dq_score = _ok / _total * 100
        if _dq_score >= 90:
            st.success(f"✅ Data Quality: {_dq_score:.0f}%  ({_ok}/{_total} indicators fresh)")
        elif _dq_score >= 70:
            st.warning(f"⚠️ Data Quality: {_dq_score:.0f}% — บาง indicator stale  ({_ok}/{_total} fresh)")
        else:
            st.error(f"❌ Data Quality: {_dq_score:.0f}% — ผล regime อาจไม่น่าเชื่อถือ  ({_ok}/{_total} fresh)")

    if _dq_data.empty:
        st.info("No data yet — run the daily job first.")
    else:
        st.dataframe(_dq_data, use_container_width=True, hide_index=True)

st.caption("FlowMacro — personal use only, not investment advice")
