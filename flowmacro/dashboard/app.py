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
        fx = yf.download("THB=X", period="2d", progress=False, auto_adjust=True)
        return float(fx["Close"].iloc[-1]) if not fx.empty else None
    except Exception:
        return None


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
    c1.metric("Confidence", f"{confidence:.1f}" if confidence is not None else "—",
              help="ความมั่นใจในการจำแนก regime (0–100)\n= |Growth−50| + |Inflation−50|\nยิ่งสูง signal ยิ่งชัด  •  < 8 = TRANSITIONING")
    c2.metric("THB/USD", f"{thb_rate:.2f}" if thb_rate is not None else "—",
              help="อัตราแลกเปลี่ยนบาทต่อดอลลาร์สหรัฐ (real-time จาก yfinance THB=X)")
    c3, c4 = st.columns(2)
    c3.metric("Growth Score", f"{growth_score:.1f}" if growth_score is not None else "—",
              help="คะแนน 0–100 วัด momentum ของเศรษฐกิจ\n> 50 = เศรษฐกิจขยายตัว  •  < 50 = ชะลอตัว\nรวม 10 indicators: yield curve, credit spread, initial claims, PMI, copper/gold, SPY/200MA, COT S&P500, COT Treasury, unemployment, GDP")
    c4.metric("Inflation Score", f"{inflation_score:.1f}" if inflation_score is not None else "—",
              help="คะแนน 0–100 วัดแรงกดดันเงินเฟ้อ\n> 50 = เงินเฟ้อสูงกว่าเป้า  •  < 50 = ต่ำกว่าเป้า\nT5YIE 2% = 50, CPI 2% = 50 (absolute scale)\nรวม 5 indicators: 5Y breakeven, DXY trend, COT gold, COT crude, CPI YoY")

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
from flowmacro.portfolio.allocator import REGIME_WEIGHTS

all_tickers = sorted({t for weights in REGIME_WEIGHTS.values() for t in weights})
palette = [
    "#2ecc71","#3498db","#e74c3c","#f1c40f","#9b59b6",
    "#1abc9c","#e67e22","#34495e","#95a5a6","#e91e63","#ff5722","#607d8b",
]
ticker_color = {t: palette[i % len(palette)] for i, t in enumerate(all_tickers)}

regime_order = ["GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"]
fig_w = go.Figure()
for ticker in all_tickers:
    y_vals = [REGIME_WEIGHTS.get(r, {}).get(ticker, 0) * 100 for r in regime_order]
    fig_w.add_trace(go.Bar(
        name=ticker, x=regime_order, y=y_vals,
        marker_color=ticker_color[ticker],
        text=[f"{v:.0f}%" if v > 0 else "" for v in y_vals],
        textposition="inside", textfont=dict(size=10),
        hovertemplate=f"{ticker}: %{{y:.1f}}%<extra></extra>",
    ))

fig_w.update_layout(
    barmode="stack",
    height=300,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(size=10)),
    margin=dict(l=10, r=10, t=30, b=10),
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(color="rgba(255,255,255,0.6)"),
    yaxis=dict(color="rgba(255,255,255,0.6)", title="% of Portfolio", ticksuffix="%",
               range=[0, 85]),
)
st.plotly_chart(fig_w, use_container_width=True, config={"displayModeBar": False})

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
