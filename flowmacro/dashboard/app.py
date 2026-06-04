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


def _quadrant_chart(growth: float, inflation: float, regime: str) -> go.Figure:
    color = _REGIME_COLOR.get(regime, "#95a5a6")
    fig = go.Figure()

    quads = [
        (0, 50, 50, 100, "rgba(0,212,255,0.08)"),     # DEFLATION — neon cyan tint
        (50, 50, 100, 100, "rgba(0,255,136,0.08)"),    # GOLDILOCKS — neon green tint
        (0, 0, 50, 50, "rgba(255,68,102,0.08)"),       # STAGFLATION — neon red tint
        (50, 0, 100, 50, "rgba(255,204,0,0.08)"),      # REFLATION — neon yellow tint
    ]
    for x0, y0, x1, y1, fill in quads:
        fig.add_shape(type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
                      fillcolor=fill, line_width=0, layer="below")

    for x, y, text in [
        (25, 75, "DEFLATION"), (75, 75, "GOLDILOCKS"),
        (25, 25, "STAGFLATION"), (75, 25, "REFLATION"),
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

    x_min = rb_df["run_date"].min()
    x_max = rb_df["run_date"].max() + pd.Timedelta(weeks=2)
    fig.update_layout(
        xaxis=dict(range=[x_min, x_max], showgrid=False,
                   tickformat="%b '%y", color="rgba(0,212,255,0.6)"),
        yaxis=dict(range=[-0.15, 1.15], showticklabels=False, showgrid=False),
        height=130, margin=dict(l=45, r=10, t=5, b=35),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
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

thb_rate   = load_thb_rate()
vix        = load_vix()
paper      = load_paper_portfolio()
days_fri   = _days_to_next_friday()

col_metrics, col_chart = st.columns([1, 1])

with col_metrics:
    # Row 1 — Confidence + Next Rebalance
    c1, c2 = st.columns(2)
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
        vix_label = "ต่ำ" if vix < 15 else ("ปกติ" if vix < 20 else ("สูง" if vix < 30 else "วิกฤต"))
        c5.metric("VIX", f"{vix:.1f}  [{vix_label}]",
                  help="CBOE Volatility Index — ความกลัวของตลาดสหรัฐ\n< 15 = สงบ  •  15–20 = ปกติ  •  20–30 = กังวล  •  > 30 = วิกฤต")
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
    _leg_cols = st.columns(5)
    for _i, (_r, _c) in enumerate(list(_REGIME_COLOR.items())[:4]):
        _leg_cols[_i].markdown(
            f"<span style='background:{_c};padding:2px 10px;border-radius:3px;"
            f"font-size:0.75rem;color:#000;font-family:monospace'>{_r[:4]}</span>",
            unsafe_allow_html=True,
        )

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

# ── AI Thesis ─────────────────────────────────────────────────────────────────
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
                        latest["regime"],
                        float(latest["confidence"]),
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

# ── Portfolio Weights ─────────────────────────────────────────────────────────
st.subheader("Portfolio Allocation by Regime")
st.caption("แต่ละ regime ถือ 80% ของ portfolio (20% cash buffer) — hover เพื่อดูสัดส่วน")
from flowmacro.portfolio.allocator import REGIME_WEIGHTS

_PIE_COLORS = [
    "#00ff88","#00d4ff","#ffcc00","#ff4466","#bf5fff",
    "#ff8800","#00ffcc","#ff66aa","#88ff00","#4488ff","#ffaa00","#aa44ff",
]
_REGIME_NEON = {
    "GOLDILOCKS":  "#00ff88",
    "REFLATION":   "#ffcc00",
    "STAGFLATION": "#ff4466",
    "DEFLATION":   "#00d4ff",
}

regime_order = ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]
pie_cols = st.columns(4)

for col, regime in zip(pie_cols, regime_order):
    weights = REGIME_WEIGHTS.get(regime, {})
    # Add 20% cash buffer as explicit slice
    labels  = list(weights.keys()) + ["Cash"]
    values  = [w * 100 for w in weights.values()] + [20.0]
    colors  = [_PIE_COLORS[i % len(_PIE_COLORS)] for i in range(len(weights))] + ["#333355"]

    fig_pie = go.Figure(go.Pie(
        labels=labels,
        values=values,
        textinfo="label+percent",
        textposition="inside",
        textfont=dict(size=10, family="monospace"),
        marker=dict(colors=colors, line=dict(color="#080c1a", width=2)),
        hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
        sort=False,
        hole=0.25,
    ))
    neon = _REGIME_NEON[regime]
    fig_pie.update_layout(
        title=dict(
            text=f"<b>{regime}</b>",
            font=dict(size=12, color=neon, family="monospace"),
            x=0.5, xanchor="center",
        ),
        showlegend=False,
        height=260,
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
st.caption("FlowMacro — personal use only, not investment advice")
