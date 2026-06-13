from datetime import date, datetime, timedelta
import pathlib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from supabase import create_client
from flowmacro.config import settings
from flowmacro.portfolio.allocator import REGIME_WEIGHTS, compute_blended_weights

st.set_page_config(page_title="FlowMacro", layout="wide")

_REGIME_ICON = {
    "GOLDILOCKS":    "🟢",
    "REFLATION":     "🟡",
    "STAGFLATION":   "🔴",
    "DEFLATION":     "🔵",
    "TRANSITIONING": "⚪",
}
_REGIME_COLOR = {
    "GOLDILOCKS":    "#00ff88",   # neon green
    "REFLATION":     "#ffcc00",   # neon yellow
    "STAGFLATION":   "#ff4466",   # neon red-pink
    "DEFLATION":     "#00d4ff",   # neon cyan
    "TRANSITIONING": "#8888aa",   # muted grey-blue
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
def load_regime_probabilities() -> dict[str, float] | None:
    """Read latest softmax regime probabilities stored by V3 weekly pipeline.
    Falls back to computing from current growth/inflation scores if V3 data not yet stored."""
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

    # Fallback: compute on the fly from stored growth/inflation scores
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
    """Load last 52 weeks of COT net speculative positions from Supabase."""
    from flowmacro.data.store import read_series
    from datetime import timedelta
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
        close = fx["Close"].squeeze()
        return float(close.dropna().iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_vix() -> float | None:
    try:
        vix = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if vix.empty:
            return None
        close = vix["Close"].squeeze()
        return float(close.dropna().iloc[-1])
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
        root = here.parent.parent.parent  # dashboard/ → flowmacro/ → repo root
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
        from datetime import timedelta
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
    """Download xgb_regime_v2_meta.json from Supabase Storage (lightweight metadata only)."""
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


def _days_to_next_friday() -> int:
    days_ahead = 4 - date.today().weekday()   # Friday = weekday 4
    return days_ahead if days_ahead > 0 else days_ahead + 7


def _prob_bars_chart(probs: dict[str, float]) -> go.Figure:
    """Horizontal bar chart — softmax probability per regime (V3), sorted highest first."""
    sorted_items = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    labels = [r for r, _ in sorted_items]
    values = [v * 100 for _, v in sorted_items]
    colors = [_REGIME_COLOR[r] for r in labels]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
        text=[f"{v:.1f}%" for v in values],
        textposition="inside",
        textfont=dict(color="#000000", size=11, family="monospace"),
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 100], showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, color="rgba(180,180,220,0.8)",
                   tickfont=dict(family="monospace", size=11),
                   autorange="reversed"),
        height=160,
        margin=dict(l=105, r=10, t=5, b=5),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _quadrant_chart(growth: float, inflation: float, regime: str) -> go.Figure:
    color = _REGIME_COLOR.get(regime, "#95a5a6")
    fig = go.Figure()

    # Quadrant mapping (x=growth, y=inflation):
    # Upper-left  (G<50, I>50) = STAGFLATION  • Upper-right (G>50, I>50) = REFLATION
    # Lower-left  (G<50, I<50) = DEFLATION    • Lower-right (G>50, I<50) = GOLDILOCKS
    quads = [
        (0,  50, 50,  100, "rgba(255,68,102,0.08)"),   # STAGFLATION — upper-left
        (50, 50, 100, 100, "rgba(255,204,0,0.08)"),    # REFLATION   — upper-right
        (0,  0,  50,  50,  "rgba(0,212,255,0.08)"),    # DEFLATION   — lower-left
        (50, 0,  100, 50,  "rgba(0,255,136,0.08)"),    # GOLDILOCKS  — lower-right
    ]
    for x0, y0, x1, y1, fill in quads:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=fill, line_width=0, layer="below")

    for x, y, text in [
        (25, 75, "STAGFLATION"), (75, 75, "REFLATION"),
        (25, 25, "DEFLATION"),   (75, 25, "GOLDILOCKS"),
    ]:
        quad_color = {"DEFLATION":"#00d4ff","GOLDILOCKS":"#00ff88",
                      "STAGFLATION":"#ff4466","REFLATION":"#ffcc00"}[text]
        fig.add_annotation(x=x, y=y, text=text, showarrow=False,
                           font=dict(size=10, color=quad_color, family="monospace"),
                           xanchor="center", yanchor="middle", opacity=0.6)

    fig.add_shape(type="line", x0=50, y0=0, x1=50, y1=100,
                  line=dict(color="rgba(0,212,255,0.3)", width=1, dash="dot"))
    fig.add_shape(type="line", x0=0, y0=50, x1=100, y1=50,
                  line=dict(color="rgba(0,212,255,0.3)", width=1, dash="dot"))

    fig.add_trace(go.Scatter(
        x=[growth], y=[inflation],
        mode="markers+text",
        text=["NOW"],
        textposition="top center",
        textfont=dict(size=10, color=color, family="monospace"),
        marker=dict(size=18, color=color,
                    line=dict(width=2, color="white"),
                    symbol="circle"),
        hovertemplate=f"Growth: {growth:.1f}<br>Inflation: {inflation:.1f}<extra></extra>",
        showlegend=False,
    ))

    fig.update_layout(
        xaxis=dict(range=[0, 100], title="Growth Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100],
                   color="rgba(0,212,255,0.6)", title_font=dict(color="rgba(0,212,255,0.8)")),
        yaxis=dict(range=[0, 100], title="Inflation Score", showgrid=False,
                   tickvals=[0, 25, 50, 75, 100],
                   color="rgba(0,212,255,0.6)", title_font=dict(color="rgba(0,212,255,0.8)")),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin=dict(l=50, r=10, t=10, b=50),
    )
    return fig


def _regime_timeline_chart(rb_df: pd.DataFrame, ml_rows: list) -> go.Figure:
    fig = go.Figure()

    def _add_band(pairs: list[tuple], y0: float, y1: float, row_label: str, x_anchor):
        if not pairs:
            return
        segments: list[tuple] = []
        cur_r, seg_start = None, None
        for dt, regime in pairs:
            if regime != cur_r:
                if cur_r is not None:
                    segments.append((seg_start, dt, cur_r))
                cur_r, seg_start = regime, dt
        if cur_r:
            segments.append((seg_start, pairs[-1][0] + pd.Timedelta(weeks=1), cur_r))

        for start, end, regime in segments:
            color = _REGIME_COLOR.get(regime, "#888888")
            fig.add_shape(type="rect", x0=start, x1=end, y0=y0, y1=y1,
                          fillcolor=color, opacity=0.75, line_width=0, layer="below")
            if (end - start).days / 7 >= 5:
                fig.add_annotation(
                    x=start + (end - start) / 2, y=(y0 + y1) / 2,
                    text=regime[:4], showarrow=False,
                    font=dict(size=8, color="rgba(0,0,0,0.8)", family="monospace"),
                    xanchor="center", yanchor="middle",
                )

        fig.add_annotation(x=x_anchor, y=(y0 + y1) / 2, text=row_label,
                           showarrow=False, xref="paper",
                           font=dict(size=9, color="rgba(180,180,220,0.7)", family="monospace"),
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
                  line=dict(color="rgba(255,255,255,0.35)", width=1, dash="dash"))

    # Always show at least 52 weeks so x-axis renders as dates even with few data points
    x_min = min(rb_df["run_date"].min(), pd.Timestamp(date.today()) - pd.Timedelta(weeks=52))
    x_max = pd.Timestamp(date.today()) + pd.Timedelta(weeks=2)
    fig.update_layout(
        xaxis=dict(range=[x_min, x_max], showgrid=False, type="date",
                   tickformat="%b '%y", color="rgba(0,212,255,0.6)"),
        yaxis=dict(range=[-0.15, 1.15], showticklabels=False, showgrid=False),
        height=130, margin=dict(l=45, r=10, t=5, b=35),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


# ── Header ───────────────────────────────────────────────────────────────────
st.title("FlowMacro — Macro Regime Dashboard")
st.caption(f"Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── Action Bar (loaded early, displayed after data loads below) ───────────────
_ab_latest   = load_latest_regime()
_ab_probs    = load_regime_probabilities()
_ab_vix      = load_vix()
_ab_days_fri = _days_to_next_friday()
_ab_thesis   = load_latest_thesis()

if _ab_latest or _ab_probs:
    _ab_dom_regime = (max(_ab_probs, key=lambda r: _ab_probs[r]) if _ab_probs else None) or (_ab_latest["regime"] if _ab_latest else "—")
    _ab_dom_prob   = (_ab_probs[_ab_dom_regime] if _ab_probs and _ab_dom_regime in _ab_probs else None)
    _ab_strength   = "WEAK" if (_ab_dom_prob or 0) < 0.35 else ("MODERATE" if (_ab_dom_prob or 0) < 0.60 else "STRONG")
    _ab_sig_color  = {"WEAK": "#ff4466", "MODERATE": "#ffcc00", "STRONG": "#00ff88"}[_ab_strength]
    _ab_neon       = _REGIME_COLOR.get(_ab_dom_regime, "#888888")
    _ab_vix_str    = f"VIX {_ab_vix:.0f}" if _ab_vix else "VIX —"
    _ab_conviction = f"Conviction {_ab_thesis['conviction']}/10" if _ab_thesis else ""
    _ab_rebal      = f"Rebalance in {_ab_days_fri}d" if _ab_days_fri > 0 else "Rebalance TODAY"

    _ab_parts = [
        f"<span style='color:{_ab_neon};font-weight:bold'>{_ab_dom_regime}</span>"
        f"<span style='color:{_ab_sig_color};font-size:0.8rem;margin-left:6px'>({_ab_strength})</span>",
        f"<span style='color:rgba(255,255,255,0.7)'>{_ab_rebal}</span>",
        f"<span style='color:rgba(255,255,255,0.7)'>{_ab_vix_str}</span>",
    ]
    if _ab_conviction:
        _ab_parts.append(f"<span style='color:rgba(255,255,255,0.7)'>{_ab_conviction}</span>")

    # B.1: Top-level action banner — clear HOLD / REBALANCE signal
    _conviction_val = _ab_thesis.get("conviction", 10) if _ab_thesis else 10
    if _ab_strength == "WEAK" or _conviction_val <= 3:
        st.error("🔴 HOLD — ไม่ต้องทำอะไร | สัญญาณอ่อน รอสัปดาห์หน้า")
    elif _ab_days_fri == 0:
        st.warning("🟡 REBALANCE TODAY — ดู trades list ด้านล่าง")
    else:
        st.success(f"🟢 HOLD — Rebalance ใน {_ab_days_fri} วัน")

    _sep = "<span style='color:rgba(255,255,255,0.2);margin:0 16px'>|</span>"
    st.markdown(
        f"<div style='background:#0d1117;border:1px solid rgba(0,212,255,0.2);border-radius:8px;"
        f"padding:10px 20px;font-family:monospace;font-size:0.95rem;margin-bottom:12px'>"
        + _sep.join(_ab_parts) +
        f"</div>",
        unsafe_allow_html=True,
    )

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

thb_rate   = load_thb_rate()
vix        = load_vix()
paper      = load_paper_portfolio()
days_fri   = _days_to_next_friday()

regime_probs = load_regime_probabilities()

# V3 dominant regime (from softmax probs) — overrides V2B hard-classify for display
if regime_probs:
    dominant_regime = max(regime_probs, key=lambda r: regime_probs[r])
    dominant_prob   = regime_probs[dominant_regime]
else:
    dominant_regime = regime
    dominant_prob   = None

display_regime = dominant_regime or regime

if display_regime:
    _neon = _REGIME_COLOR.get(display_regime, "#888888")

    # Signal strength: 25% = no signal (uniform), 100% = perfect signal
    # Normalize to 0–100% range for display
    if dominant_prob is not None:
        _strength_pct = max(0.0, (dominant_prob - 0.25) / 0.75) * 100
        if _strength_pct < 20:
            _sig_label, _sig_color, _sig_action = "WEAK", "#ff4466", "ถือ portfolio ปัจจุบัน — รอ signal ชัดขึ้น"
        elif _strength_pct < 50:
            _sig_label, _sig_color, _sig_action = "MODERATE", "#ffcc00", "เริ่ม lean ตาม regime — ยังไม่ full position"
        else:
            _sig_label, _sig_color, _sig_action = "STRONG", "#00ff88", "signal ชัด — ดำเนินการตาม regime ได้เลย"
    else:
        _strength_pct, _sig_label, _sig_color, _sig_action = 0, "NO DATA", "#888888", ""

    # B.2: badge label + background color driven by dominant_prob thresholds
    if dominant_prob is not None:
        if dominant_prob >= 0.60:
            _badge_label = display_regime
            _badge_bg    = _neon
        elif dominant_prob >= 0.40:
            _badge_label = f"{display_regime} (MODERATE)"
            _badge_bg    = "#ffaa00"
        else:
            _badge_label = "TRANSITIONING"
            _badge_bg    = "#8888aa"
    else:
        _badge_label = display_regime or "—"
        _badge_bg    = _neon

    _badge_opacity = "0.5" if _sig_label == "WEAK" else ("0.8" if _sig_label == "MODERATE" else "1.0")
    _badge_border  = f"border:2px dashed {_badge_bg};" if _sig_label == "WEAK" else ""
    st.markdown(
        f"<span style='background:{_badge_bg};color:#000;font-family:monospace;font-weight:bold;"
        f"font-size:1.3rem;padding:4px 18px;border-radius:6px;opacity:{_badge_opacity};{_badge_border}'>"
        f"{_badge_label}</span>"
        f"<span style='color:rgba(255,255,255,0.4);font-size:0.85rem;margin-left:12px'>as of {run_date or '—'}</span>",
        unsafe_allow_html=True,
    )
    st.caption(_REGIME_DESC.get(display_regime, ""))

    # Signal strength bar
    st.markdown(
        f"<div style='margin-top:8px;margin-bottom:2px'>"
        f"<span style='color:{_sig_color};font-family:monospace;font-weight:bold;font-size:0.9rem'>"
        f"Signal: {_sig_label}</span>"
        f"<span style='color:rgba(255,255,255,0.4);font-size:0.8rem;margin-left:10px'>{_sig_action}</span>"
        f"</div>"
        f"<div style='background:#1a1a2e;border-radius:4px;height:6px;width:300px'>"
        f"<div style='background:{_sig_color};height:100%;width:{_strength_pct:.0f}%;border-radius:4px;"
        f"transition:width 0.3s'></div></div>"
        f"<div style='display:flex;width:300px;justify-content:space-between;"
        f"font-size:0.7rem;color:rgba(255,255,255,0.25);font-family:monospace;margin-top:2px'>"
        f"<span>unclear</span><span>moderate</span><span>strong</span></div>",
        unsafe_allow_html=True,
    )
else:
    st.warning("NO DATA — Run weekly job first")

col_metrics, col_chart = st.columns([1, 1])

with col_metrics:
    # Row 1 — Dominant Prob + Next Rebalance
    c1, c2 = st.columns(2)
    if dominant_prob is not None:
        c1.metric("Dominant Prob", f"{dominant_prob:.0%}",
                  help="ความน่าจะเป็นของ dominant regime จาก V3 softmax\n100% = signal ชัดมาก  •  25% = ทุก regime เท่ากัน (สับสนที่สุด)")
    else:
        c1.metric("Confidence", f"{confidence:.1f}" if confidence is not None else "—",
                  help="ความมั่นใจในการจำแนก regime (0–100)\n= |Growth−50| + |Inflation−50|\nยิ่งสูง signal ยิ่งชัด  •  < 8 = TRANSITIONING")
    c2.metric("Next Rebalance",
              f"{days_fri} day{'s' if days_fri != 1 else ''}" if days_fri > 0 else "Today (Friday!)",
              help="จำนวนวันถึง Friday — วัน rebalance ถัดไปของ weekly job\nGitHub Actions รัน 08:30 Bangkok")

    # Row 2 — Growth + Inflation
    c3, c4 = st.columns(2)
    c3.metric("Growth Score", f"{growth_score:.1f}" if growth_score is not None else "—",
              help="คะแนน 0–100 วัด momentum ของเศรษฐกิจ\n> 50 = เศรษฐกิจขยายตัว  •  < 50 = ชะลอตัว\nรวม 10 indicators: yield curve, credit spread, initial claims, PMI, copper/gold, SPY/200MA, COT S&P500, COT Treasury, unemployment, GDP")
    c4.metric("Inflation Score", f"{inflation_score:.1f}" if inflation_score is not None else "—",
              help="คะแนน 0–100 วัดแรงกดดันเงินเฟ้อ\n> 50 = เงินเฟ้อสูงกว่าเป้า  •  < 50 = ต่ำกว่าเป้า\nT5YIE 2% = 50, CPI 2% = 50 (absolute scale)\nรวม 5 indicators: 5Y breakeven, DXY trend, COT gold, COT crude, CPI YoY")

    # Row 3 — VIX + Paper Portfolio
    c5, c6 = st.columns(2)
    if vix is not None:
        vix_label = "ต่ำ" if vix < 15 else ("ปกติ" if vix < 25 else ("สูง" if vix < 35 else "วิกฤต"))
        c5.metric("VIX", f"{vix:.1f}  [{vix_label}]",
                  help="CBOE Volatility Index — ความกลัวของตลาดสหรัฐ\n< 15 = สงบ  •  15–25 = ปกติ  •  25–35 = สูง  •  > 35 = วิกฤต")
    else:
        c5.metric("VIX", "—")

    if paper:
        thb_equiv = f" / ฿{paper['value_usd'] * thb_rate:,.0f}" if thb_rate else ""
        c6.metric("Paper Portfolio",
                  f"${paper['value_usd']:,.0f}{thb_equiv}",
                  delta=f"{paper['pnl_pct']:+.1f}% since start",
                  delta_color="normal",
                  help=f"Virtual portfolio เริ่มต้น $3,000 (≈ ฿{3000*thb_rate:,.0f} ที่ rate {thb_rate:.2f})\nอัปเดต: {paper['as_of']}" if thb_rate else "Virtual portfolio เริ่มต้น $3,000")
    else:
        c6.metric("Paper Portfolio", "Initialised",
                  help="Paper portfolio $3,000 เพิ่งเริ่มต้น\nP&L จะแสดงหลังจาก weekly job รันครั้งถัดไป (Friday)")


with col_chart:
    if growth_score is not None and inflation_score is not None:
        st.plotly_chart(
            _quadrant_chart(growth_score, inflation_score, display_regime or ""),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    else:
        st.info("Run weekly job to populate regime scores.")

    if regime_probs:
        st.caption("Regime probabilities (V3 softmax)")
        st.plotly_chart(
            _prob_bars_chart(regime_probs),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    elif latest:
        st.caption("Regime probabilities — run V3 weekly pipeline to populate")

st.divider()

# ── AI Macro Thesis ───────────────────────────────────────────────────────────
st.subheader("AI Macro Thesis")

thesis = load_latest_thesis()

col_thesis_hdr, col_thesis_btn = st.columns([3, 1])
with col_thesis_hdr:
    if thesis:
        st.caption(f"Generated: {thesis.get('run_date','—')}  |  Regime: {thesis.get('regime','—')}  |  Model: {thesis.get('model','—')}")
    else:
        st.caption("No thesis yet — run weekly job or click Generate.")

with col_thesis_btn:
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
        f"<span style='font-size:2rem;font-weight:bold;color:{conv_color}'>"
        f"Conviction {conv}/10</span>",
        unsafe_allow_html=True,
    )
    t_col1, t_col2 = st.columns(2)
    with t_col1:
        st.markdown("**คำแนะนำ**")
        st.info(thesis.get("recommendation", "—"))
        st.markdown("**เหตุผล**")
        st.write(thesis.get("reasoning", "—"))
    with t_col2:
        st.markdown("**ความเสี่ยง**")
        st.warning(thesis.get("risks", "—"))

st.divider()

# ── Regime History Timeline ───────────────────────────────────────────────────
st.subheader("Regime History (52 weeks)")
_hist_df  = load_regime_history(weeks=52)
_ml_shad  = load_ml_shadow()

if _hist_df.empty:
    st.info("No regime history — run weekly job first.")
else:
    st.plotly_chart(
        _regime_timeline_chart(_hist_df, _ml_shad.get("rows", [])),
        use_container_width=True, config={"displayModeBar": False},
    )
    _chips = " ".join(
        f"<span style='background:{_c};padding:2px 10px;border-radius:3px;"
        f"font-size:0.75rem;color:#000;font-family:monospace;margin-right:4px'>{_r[:4]}</span>"
        for _r, _c in list(_REGIME_COLOR.items())[:4]
    )
    st.markdown(_chips, unsafe_allow_html=True)

st.divider()

# ── ML Shadow Mode ────────────────────────────────────────────────────────────
st.subheader("ML Shadow Mode")
st.caption("XGBoost model run ควบคู่ rule-based ทุกศุกร์ — ยังไม่กระทบ portfolio จนกว่าจะผ่าน graduation criteria")

if not _ml_shad.get("active"):
    st.warning("ML shadow unavailable — check regime_history_ml table.")
elif _ml_shad["n_weeks"] == 0:
    st.info("Shadow mode active — predictions log every Friday. No data yet.")
else:
    _n       = _ml_shad["n_weeks"]
    _rate    = _ml_shad["agreement_rate"]
    _latest  = _ml_shad["latest"]
    _ml_r    = _latest["ml_regime"]
    _rb_r    = _latest["rb_regime"]
    _agrees  = _latest["agrees"]
    _ml_c    = _latest.get("ml_confidence") or 0

    _col_a, _col_b, _col_c = st.columns([1, 1, 1])

    with _col_a:
        st.markdown("**Latest Prediction**")
        _ml_col = _REGIME_COLOR.get(_ml_r, "#888")
        _rb_col = _REGIME_COLOR.get(_rb_r, "#888")
        st.markdown(
            f"ML:&nbsp;&nbsp;<span style='color:{_ml_col};font-weight:bold'>{_ml_r}</span> "
            f"<span style='font-size:0.8rem;color:rgba(255,255,255,0.5)'>({_ml_c:.1f})</span><br>"
            f"Rule: <span style='color:{_rb_col};font-weight:bold'>{_rb_r}</span>",
            unsafe_allow_html=True,
        )
        _agree_col  = "#00ff88" if _agrees else "#ff4466"
        _agree_text = "Agrees" if _agrees else "Disagrees"
        st.markdown(
            f"<span style='color:{_agree_col}'>{_agree_text}</span>"
            f"<span style='color:rgba(255,255,255,0.4);font-size:0.8rem'> — {_latest['run_date']}</span>",
            unsafe_allow_html=True,
        )

    with _col_b:
        _bar_col = "#00ff88" if _rate >= 70 else ("#ffcc00" if _rate >= 50 else "#ff4466")
        st.markdown(f"**Agreement Rate ({_n} week{'s' if _n != 1 else ''})**")
        st.markdown(
            f"<div style='background:#1a1a2e;border-radius:4px;height:10px;width:100%;margin-bottom:6px'>"
            f"<div style='background:{_bar_col};height:100%;width:{min(_rate,100):.0f}%;border-radius:4px'></div></div>"
            f"<span style='font-size:1.6rem;font-weight:bold;color:{_bar_col}'>{_rate:.0f}%</span>"
            f"<span style='color:rgba(255,255,255,0.4);font-size:0.8rem'> / 70% target</span>",
            unsafe_allow_html=True,
        )

    with _col_c:
        _weeks_left = max(0, 26 - _n)
        st.markdown("**Graduation (6 months)**")
        _agree_sym = "<span style='color:#00ff88'>OK</span>" if _rate >= 70 \
                     else f"<span style='color:#ffcc00'>{_rate:.0f}% (need 70%)</span>"
        _period_sym = f"{_n}/26 weeks" if _weeks_left > 0 \
                      else "<span style='color:#00ff88'>Complete</span>"
        st.markdown(
            f"Agreement: {_agree_sym}<br>"
            f"NBER 5/6:  <span style='color:#00ff88'>OK</span> (offline)<br>"
            f"Live:      {_period_sym}",
            unsafe_allow_html=True,
        )

st.divider()

# ── XGBoost v2 Development ────────────────────────────────────────────────────
_V1_BASELINE = 0.663
_v2 = load_v2_bundle()

st.subheader("XGBoost v2 Development")
st.caption("31 features (17 เดิม + 14 leading indicators) — shadow mode, targeting Dec 2026 graduation")

if not _v2["ok"]:
    st.info("v2 model bundle not found — run scripts/train_regime_xgb_v2.py first.")
else:
    _wf         = _v2["wf_accuracy"]
    _nber       = _v2["nber_passed"]
    _nber_total = _v2.get("nber_total", 6)
    _nfeat      = _v2["n_features"]
    _ratio      = round(712 / _nfeat, 1) if _nfeat else 0

    _acc_ok   = isinstance(_wf, float) and _wf > _V1_BASELINE
    _nber_ok  = isinstance(_nber, int) and _nber == _nber_total and _nber_total >= 3
    _ratio_ok = _ratio >= 20
    _criteria_met = sum([_acc_ok, _nber_ok, _ratio_ok])

    _c1, _c2, _c3, _c4 = st.columns(4)

    with _c1:
        _wf_pct  = f"{_wf:.1%}" if isinstance(_wf, float) else "—"
        _wf_col  = "#00ff88" if _acc_ok else ("#ffcc00" if isinstance(_wf, float) and _wf > 0.60 else "#ff4466")
        st.markdown(
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.5)'>Walk-forward Accuracy</div>"
            f"<div style='font-size:1.8rem;font-weight:bold;color:{_wf_col}'>{_wf_pct}</div>"
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.4)'>baseline {_V1_BASELINE:.1%}</div>",
            unsafe_allow_html=True,
        )

    with _c2:
        _nber_str = f"{_nber}/{_nber_total}" if isinstance(_nber, int) else "—"
        _nber_col = "#00ff88" if _nber_ok else "#ff4466"
        st.markdown(
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.5)'>NBER Episodes</div>"
            f"<div style='font-size:1.8rem;font-weight:bold;color:{_nber_col}'>{_nber_str}</div>"
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.4)'>w/ data (pre-2013 skipped)</div>",
            unsafe_allow_html=True,
        )

    with _c3:
        _ratio_col = "#00ff88" if _ratio_ok else "#ff4466"
        st.markdown(
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.5)'>Sample/Feature</div>"
            f"<div style='font-size:1.8rem;font-weight:bold;color:{_ratio_col}'>{_ratio}:1</div>"
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.4)'>{_nfeat} features, need &ge;20:1</div>",
            unsafe_allow_html=True,
        )

    with _c4:
        _status_col  = "#00ff88" if _criteria_met == 3 else ("#ffcc00" if _criteria_met >= 2 else "#ff4466")
        _status_text = "Ready to promote" if _criteria_met == 3 else f"{_criteria_met}/3 criteria met"
        st.markdown(
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.5)'>Status</div>"
            f"<div style='font-size:1.1rem;font-weight:bold;color:{_status_col}'>{_status_text}</div>"
            f"<div style='font-size:0.75rem;color:rgba(255,255,255,0.4)'>graduation target: Dec 2026</div>",
            unsafe_allow_html=True,
        )

    # Progress bar
    _bar_w   = int(_criteria_met / 3 * 100)
    _bar_col = "#00ff88" if _criteria_met == 3 else ("#ffcc00" if _criteria_met >= 2 else "#ff4466")
    _missing = []
    if not _acc_ok:
        _missing.append(f"accuracy {_wf:.1%} < {_V1_BASELINE:.1%}" if isinstance(_wf, float) else "accuracy —")
    if not _nber_ok:
        _missing.append(f"NBER {_nber}/{_nber_total} not all passed" if isinstance(_nber, int) else "NBER —")
    if not _ratio_ok:
        _missing.append(f"ratio {_ratio}:1 < 20:1")
    _miss_str = "  ·  ".join(_missing) if _missing else "all criteria met"
    st.markdown(
        f"<div style='background:#1a1a2e;border-radius:4px;height:8px;width:100%;margin:10px 0 4px'>"
        f"<div style='background:{_bar_col};height:100%;width:{_bar_w}%;border-radius:4px'></div></div>"
        f"<span style='font-size:0.75rem;color:rgba(255,255,255,0.4)'>Missing: {_miss_str}"
        f"  ·  retrained quarterly (Jan/Apr/Jul/Oct) via GitHub Actions</span>",
        unsafe_allow_html=True,
    )

st.divider()

# ── Returns vs Benchmark ─────────────────────────────────────────────────────
st.subheader("Returns vs Benchmark")

_BM_START_RV    = "2021-01-01"
_live_weeks_rv  = (date.today() - date(2026, 6, 3)).days // 7
_oos_rv         = load_backtest_oos()
_spy_rv         = load_ticker_prices_rv("SPY", start=_BM_START_RV)
_agg_rv         = load_ticker_prices_rv("AGG", start=_BM_START_RV)
_pp_rv          = load_paper_portfolio()
_ppb_rv         = load_portfolio_b_live()


def _fmt_ret(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'+'if v >= 0 else ''}{v:.1f}%"


def _oos_ret(start: str) -> float | None:
    if _oos_rv.empty:
        return None
    sub = _oos_rv[_oos_rv.index >= pd.Timestamp(start)].dropna()
    if len(sub) < 2:
        return None
    return (float(sub.iloc[-1]) / float(sub.iloc[0]) - 1) * 100


def _bm_spy(start: str) -> float | None:
    sub = _spy_rv[_spy_rv.index >= pd.Timestamp(start)].dropna()
    if len(sub) < 2:
        return None
    return (float(sub.iloc[-1]) / float(sub.iloc[0]) - 1) * 100


def _bm_6040(start: str) -> float | None:
    s = pd.Timestamp(start)
    spy_s = _spy_rv[_spy_rv.index >= s].dropna()
    agg_s = _agg_rv[_agg_rv.index >= s].dropna()
    if len(spy_s) < 2 or len(agg_s) < 2:
        return None
    return 0.60 * (float(spy_s.iloc[-1] / spy_s.iloc[0]) - 1) * 100 + \
           0.40 * (float(agg_s.iloc[-1] / agg_s.iloc[0]) - 1) * 100


_rv_periods = [
    ("YTD",                              "2026-01-01",                         "backtest OOS"),
    ("1Y",  str(date.today() - timedelta(days=365)),   "backtest OOS"),
    ("2Y",  str(date.today() - timedelta(days=730)),   "backtest OOS"),
    ("3Y",  str(date.today() - timedelta(days=1095)),  "backtest OOS"),
    ("5Y",  str(date.today() - timedelta(days=1825)),  "backtest OOS"),
    (f"Since live ({_live_weeks_rv}w)", "2026-06-03",  "LIVE"),
]

_rv_rows = []
for _pl, _ps, _src in _rv_periods:
    if _src == "LIVE":
        _live_ret_a = _pp_rv["pnl_pct"]  if _pp_rv  else None
        _live_ret_b = _ppb_rv["pnl_pct"] if _ppb_rv else None
        _fm_cell    = f"{_fmt_ret(_live_ret_a)} (live)" if _live_ret_a is not None else "—"
        _ml_cell    = f"{_fmt_ret(_live_ret_b)} (live)" if _live_ret_b is not None else "—"
    else:
        _fm_cell = _fmt_ret(_oos_ret(_ps))
        _ml_cell = "—"   # no OOS backtest for ML-blend

    _rv_rows.append({
        "Period":              _pl,
        "Portfolio A (V3)":   _fm_cell,
        "Portfolio B (ML)":   _ml_cell,
        "Source":             _src,
        "SPY":                _fmt_ret(_bm_spy(_ps)),
        "60/40 (SPY+AGG)":   _fmt_ret(_bm_6040(_ps)),
    })

st.dataframe(pd.DataFrame(_rv_rows), use_container_width=True, hide_index=True)
st.caption(
    "Portfolio A (V3) YTD–5Y = **backtest OOS** (out-of-sample 2020–2026)  "
    "•  Portfolio B (ML) Since live = ผลจริง ML-blend 30% (เพิ่งเริ่ม — ต้องรอ 26 สัปดาห์)  "
    "•  Benchmark = yfinance actual prices"
)

st.divider()

# ── COT Signals ───────────────────────────────────────────────────────────────
st.subheader("COT — Net Speculative Positioning")
st.caption(
    "**COT (Commitments of Traders)** = รายงานของ CFTC (ออกทุกศุกร์) แสดง net position ของ "
    "Non-Commercial traders (hedge funds / speculators) ในตลาด futures  "
    "**บวก** = long net (คาดราคาขึ้น)  •  **ลบ** = short net (คาดราคาลง)  •  หน่วย: จำนวน contracts"
)
cot_data = load_cot_series()

if not cot_data:
    st.info("No COT data yet — run weekly job first.")
else:
    cot_cols = st.columns(len(cot_data))
    colors = {"S&P 500": "#2ecc71", "10Y Treasury": "#3498db", "Gold": "#f1c40f", "Crude Oil": "#e67e22"}
    def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    for col, (label, series) in zip(cot_cols, cot_data.items()):
        with col:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=series.index, y=series.values,
                mode="lines", line=dict(color=colors.get(label, "#95a5a6"), width=2),
                fill="tozeroy", fillcolor=_hex_to_rgba(colors.get(label, "#95a5a6")),
                hovertemplate="%{x|%Y-%m-%d}<br>Net: %{y:,.0f} contracts<extra></extra>",
                showlegend=False,
            ))
            fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.3)", width=1, dash="dot"))
            last_val = series.iloc[-1] if not series.empty else 0
            fig.update_layout(
                title=dict(text=f"{label}<br><sup>{last_val:+,.0f} contracts</sup>", font=dict(size=12)),
                height=200, margin=dict(l=5, r=5, t=45, b=30),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, color="rgba(255,255,255,0.4)"),
                yaxis=dict(showgrid=False, color="rgba(255,255,255,0.4)", tickformat=".2s",
                           title="contracts", title_standoff=4),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.divider()

# ── Portfolio Allocation ──────────────────────────────────────────────────────
st.subheader("Portfolio Allocation — ตอนนี้ถืออะไรบ้าง")
st.caption("Blended allocation = ถ่วงน้ำหนักทุก regime ตาม softmax probability พร้อมกัน ไม่ใช่ hard switch")

_ASSET_COLOR = {
    "SPY": "#00ff88", "QQQ": "#00cc66", "IWM": "#009944", "EFA": "#44ffaa", "EEM": "#88ffcc",
    "BTC-USD": "#bf5fff",
    "TLT": "#00d4ff", "IEF": "#0099cc", "SHY": "#006699",
    "GLD": "#ffcc00", "SLV": "#ffaa44", "DBC": "#ff8800", "UUP": "#ff6600",
    "Cash": "#333355",
}
_REGIME_NEON = {
    "GOLDILOCKS": "#00ff88", "REFLATION": "#ffcc00",
    "STAGFLATION": "#ff4466", "DEFLATION": "#00d4ff",
}
_PIE_COLORS = [
    "#00ff88","#00d4ff","#ffcc00","#ff4466","#bf5fff",
    "#ff8800","#00ffcc","#ff66aa","#88ff00","#4488ff","#ffaa00","#aa44ff",
]

# Compute current blended weights from regime probs
_blend: dict[str, float] | None = None
if regime_probs:
    try:
        _raw_blend = compute_blended_weights(regime_probs)
        _blend = {k: v for k, v in _raw_blend.items() if v > 0.001}
        _blend["Cash"] = _blend.get("Cash", 0.0) + 0.20  # add 20% cash buffer
    except Exception:
        _blend = None

if _blend:
    # ─ Plain-language category summary ────────────────────────────────────────
    _EQ  = {"SPY", "QQQ", "IWM", "EFA", "EEM", "BTC-USD"}
    _BD  = {"TLT", "IEF", "SHY"}
    _CMD = {"GLD", "SLV", "DBC", "UUP"}
    _eq_pct   = sum(v for k, v in _blend.items() if k in _EQ)  * 100
    _bd_pct   = sum(v for k, v in _blend.items() if k in _BD)  * 100
    _cm_pct   = sum(v for k, v in _blend.items() if k in _CMD) * 100
    _cash_pct = _blend.get("Cash", 0.0) * 100
    _dom_r    = display_regime or "—"
    _dom_rc   = _REGIME_COLOR.get(_dom_r, "#888888")
    _dom_rp   = f"{dominant_prob:.0%}" if dominant_prob else "—"
    _regime_context = {
        "GOLDILOCKS":    "เศรษฐกิจขยายตัว เงินเฟ้อต่ำ → เน้นหุ้น risk-on",
        "REFLATION":     "เศรษฐกิจฟื้นตัว เงินเฟ้อสูง → เน้น commodities + ตลาดเกิดใหม่",
        "STAGFLATION":   "เศรษฐกิจชะลอ เงินเฟ้อสูง → เน้นทอง + commodities + USD",
        "DEFLATION":     "เศรษฐกิจชะลอ เงินเฟ้อต่ำ → เน้นพันธบัตร + USD",
        "TRANSITIONING": "สัญญาณสับสน → ถือ defensive assets รอ regime ชัดขึ้น",
    }.get(_dom_r, "")
    st.markdown(
        f"<div style='background:#0d1117;border:1px solid rgba(0,212,255,0.15);"
        f"border-radius:8px;padding:12px 20px;margin-bottom:14px'>"
        f"<div style='margin-bottom:6px'>"
        f"<span style='color:{_dom_rc};font-weight:bold;font-family:monospace;font-size:1.05rem'>{_dom_r}</span>"
        f"<span style='color:rgba(255,255,255,0.4);font-size:0.85rem;margin-left:8px'>({_dom_rp} dominant)</span>"
        f"<span style='color:rgba(255,255,255,0.6);font-size:0.9rem;margin-left:12px'>{_regime_context}</span>"
        f"</div>"
        f"<div style='font-family:monospace;font-size:0.95rem;display:flex;gap:24px;flex-wrap:wrap'>"
        f"<span><span style='color:rgba(255,255,255,0.4)'>หุ้น</span>&nbsp;"
        f"<span style='color:#00ff88;font-weight:bold'>{_eq_pct:.0f}%</span></span>"
        f"<span><span style='color:rgba(255,255,255,0.4)'>พันธบัตร</span>&nbsp;"
        f"<span style='color:#00d4ff;font-weight:bold'>{_bd_pct:.0f}%</span></span>"
        f"<span><span style='color:rgba(255,255,255,0.4)'>Commodities</span>&nbsp;"
        f"<span style='color:#ffcc00;font-weight:bold'>{_cm_pct:.0f}%</span></span>"
        f"<span><span style='color:rgba(255,255,255,0.4)'>เงินสด</span>&nbsp;"
        f"<span style='color:#666699;font-weight:bold'>{_cash_pct:.0f}%</span></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    sorted_blend = sorted(_blend.items(), key=lambda x: x[1], reverse=True)
    assets = [a for a, _ in sorted_blend]
    pcts   = [w * 100 for _, w in sorted_blend]
    colors = [_ASSET_COLOR.get(a, "#888888") for a in assets]

    fig_blend = go.Figure(go.Bar(
        x=pcts,
        y=assets,
        orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
        text=[f"{v:.1f}%" for v in pcts],
        textposition="inside",
        textfont=dict(color="#000000", size=11, family="monospace"),
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig_blend.update_layout(
        xaxis=dict(range=[0, max(pcts) * 1.15], showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, color="rgba(180,180,220,0.9)",
                   tickfont=dict(family="monospace", size=11), autorange="reversed"),
        height=max(200, len(assets) * 32),
        margin=dict(l=80, r=10, t=5, b=5),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    st.plotly_chart(fig_blend, use_container_width=True, config={"displayModeBar": False})
    st.caption("Blended allocation = weighted average ของทุก regime ตาม softmax probability  •  Cash 20% buffer รวมแล้ว")
else:
    st.info("Run weekly job to populate regime scores.")

with st.expander("Per-Regime Reference Weights", expanded=False):
    st.caption("แต่ละ regime ถือ 80% ของ portfolio (20% cash buffer) — ใช้เป็น reference เท่านั้น, portfolio จริงคือ blended ด้านบน")
    regime_order = ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]
    pie_cols = st.columns(4)
    for col, regime in zip(pie_cols, regime_order):
        weights = REGIME_WEIGHTS.get(regime, {})
        labels  = list(weights.keys()) + ["Cash"]
        values  = [w * 100 for w in weights.values()] + [20.0]
        p_colors = [_PIE_COLORS[i % len(_PIE_COLORS)] for i in range(len(weights))] + ["#333355"]
        fig_pie = go.Figure(go.Pie(
            labels=labels, values=values,
            textinfo="label+percent", textposition="inside",
            textfont=dict(size=10, family="monospace"),
            marker=dict(colors=p_colors, line=dict(color="#080c1a", width=2)),
            hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
            sort=False, hole=0.25,
        ))
        neon = _REGIME_NEON[regime]
        fig_pie.update_layout(
            title=dict(text=f"<b>{regime}</b>",
                       font=dict(size=12, color=neon, family="monospace"), x=0.5, xanchor="center"),
            showlegend=False, height=260,
            margin=dict(l=5, r=5, t=35, b=5),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        with col:
            st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})

with st.expander("คำอธิบาย Ticker Symbols", expanded=False):
    st.markdown("""
| Ticker | ชื่อเต็ม | ประเภท |
|--------|----------|--------|
| **SPY** | SPDR S&P 500 ETF | หุ้นสหรัฐ Large Cap |
| **QQQ** | Invesco Nasdaq 100 ETF | หุ้นเทคโนโลยีสหรัฐ |
| **IWM** | iShares Russell 2000 ETF | หุ้นสหรัฐ Small Cap |
| **EFA** | iShares MSCI EAFE ETF | หุ้นตลาดพัฒนาแล้ว (ยุโรป/ญี่ปุ่น) |
| **EEM** | iShares MSCI Emerging Markets ETF | หุ้นตลาดเกิดใหม่ |
| **TLT** | iShares 20+ Year Treasury Bond ETF | พันธบัตรรัฐบาลสหรัฐ อายุ 20+ ปี |
| **IEF** | iShares 7-10 Year Treasury Bond ETF | พันธบัตรรัฐบาลสหรัฐ อายุ 7-10 ปี |
| **GLD** | SPDR Gold Shares ETF | ทองคำ |
| **SLV** | iShares Silver Trust ETF | เงิน (Silver) |
| **DBC** | Invesco DB Commodity Index ETF | สินค้าโภคภัณฑ์หลากหลาย |
| **USO** | United States Oil Fund ETF | น้ำมันดิบ WTI |
| **UUP** | Invesco DB US Dollar Index ETF | ดัชนีค่าเงินดอลลาร์ (DXY) |
""")

st.divider()

# ── C.4: Data Quality Score ───────────────────────────────────────────────────
_dq_data = load_staleness()
if not _dq_data.empty:
    _ok      = int((_dq_data["Status"].str.startswith("✅")).sum())
    _total   = len(_dq_data)
    _dq_score = _ok / _total * 100
    if _dq_score >= 90:
        st.success(f"✅ Data Quality: {_dq_score:.0f}%  ({_ok}/{_total} indicators fresh)")
    elif _dq_score >= 70:
        st.warning(f"⚠️ Data Quality: {_dq_score:.0f}% — บาง indicator stale  ({_ok}/{_total} fresh) | ดูรายละเอียดด้านล่าง")
    else:
        st.error(f"❌ Data Quality: {_dq_score:.0f}% — ผล regime อาจไม่น่าเชื่อถือ  ({_ok}/{_total} fresh) | รัน daily job")

with st.expander("Data Staleness — Indicator freshness check", expanded=False):
    if _dq_data.empty:
        st.info("No data yet — run the daily job first.")
    else:
        st.dataframe(_dq_data, use_container_width=True, hide_index=True)

st.caption("FlowMacro — personal use only, not investment advice")
