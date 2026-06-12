"""Paper Trading P&L Tracker — FlowMacro virtual portfolio."""
from datetime import date, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Paper Trading — FlowMacro", layout="wide")
st.title("Paper Trading P&L Tracker")

_INITIAL_CASH = 3_000.0
_REGIME_COLORS = {
    "GOLDILOCKS":   "#2ecc71",
    "REFLATION":    "#f39c12",
    "STAGFLATION":  "#e74c3c",
    "DEFLATION":    "#3498db",
    "TRANSITIONING": "#95a5a6",
}


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=300)
def load_paper_values() -> pd.Series:
    try:
        from flowmacro.data.store import read_series
        s = read_series("paper_total_value", start="2020-01-01")
        return s.sort_index()
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=300)
def load_regime_history() -> pd.DataFrame:
    try:
        r = _db().table("regime_history").select("run_date,regime,confidence") \
              .order("run_date", desc=False).execute()
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        df["run_date"] = pd.to_datetime(df["run_date"])
        return df.set_index("run_date")
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_ticker_prices(ticker: str, start: str) -> pd.Series:
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        return df["Close"].squeeze().dropna()
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=300)
def load_regime_probs() -> dict[str, float] | None:
    try:
        from flowmacro.data.store import read_series
        probs: dict[str, float] = {}
        for regime, sid in [
            ("GOLDILOCKS",  "regime_prob_goldilocks"),
            ("REFLATION",   "regime_prob_reflation"),
            ("STAGFLATION", "regime_prob_stagflation"),
            ("DEFLATION",   "regime_prob_deflation"),
        ]:
            s = read_series(sid, start=str(date.today() - timedelta(days=8)))
            if not s.empty:
                probs[regime] = float(s.dropna().iloc[-1])
        return probs if len(probs) == 4 else None
    except Exception:
        return None


values    = load_paper_values()
regimes   = load_regime_history()

if values.empty:
    st.info("ยังไม่มีข้อมูล paper trading — รัน weekly job ก่อน (`python -m flowmacro.scheduler.weekly`)")
    st.stop()

# ── Current stats ─────────────────────────────────────────────────────────────
current_value = float(values.iloc[-1])
last_date     = values.index[-1].date()
total_pnl     = current_value - _INITIAL_CASH
total_pct     = (current_value / _INITIAL_CASH - 1) * 100
weeks_tracked = len(values) - 1  # first entry = initialisation

week_pnl = week_pct = None
if len(values) >= 2:
    prev_val  = float(values.iloc[-2])
    week_pnl  = current_value - prev_val
    week_pct  = (current_value / prev_val - 1) * 100 if prev_val else None

# Current regime from regime_history
current_regime = "—"
if not regimes.empty:
    current_regime = str(regimes["regime"].iloc[-1])
regime_color = _REGIME_COLORS.get(current_regime, "#95a5a6")

st.caption(
    f"Start: 2026-06-03  |  Initial capital: ${_INITIAL_CASH:,.0f}  |  "
    f"Last update: {last_date}  |  Weeks tracked: {weeks_tracked}"
)

# ── Metric cards ──────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Portfolio Value",
    f"${current_value:,.2f}",
    delta=f"${total_pnl:+,.2f} total",
    help="Current paper portfolio value (USD)",
)
c2.metric(
    "Total Return",
    f"{total_pct:+.2f}%",
    help=f"Since inception (${_INITIAL_CASH:,.0f})",
)
c3.metric(
    "Last Week P&L",
    f"${week_pnl:+,.2f}" if week_pnl is not None else "—",
    delta=f"{week_pct:+.2f}%" if week_pct is not None else None,
    help="Week-over-week dollar gain/loss",
)
with c4:
    st.markdown("**Current Regime**")
    st.markdown(
        f'<span style="color:{regime_color};font-size:1.2rem;font-weight:700">'
        f'{current_regime}</span>',
        unsafe_allow_html=True,
    )
    if not regimes.empty:
        conf = float(regimes["confidence"].iloc[-1])
        st.caption(f"Confidence: {conf:.1f}%")

if weeks_tracked < 4:
    st.info(
        f"Paper trading เพิ่งเริ่ม — {weeks_tracked} สัปดาห์ / 4–8 สัปดาห์ที่ต้องรอก่อนประเมินผล"
    )

st.divider()

# ── Equity curve ──────────────────────────────────────────────────────────────
st.subheader("Equity Curve")

fig = go.Figure()

fig.add_hline(
    y=_INITIAL_CASH,
    line_dash="dot",
    line_color="rgba(255,255,255,0.25)",
    annotation_text=f"Initial ${_INITIAL_CASH:,.0f}",
    annotation_position="bottom right",
)

fig.add_trace(go.Scatter(
    x=[ts.strftime("%Y-%m-%d") for ts in values.index],
    y=values.values,
    name="Paper Portfolio",
    mode="lines+markers",
    line=dict(color="#2ecc71", width=2),
    marker=dict(size=7),
    hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Value: $%{y:,.2f}<extra></extra>",
))

fig.update_layout(
    yaxis_title="Portfolio Value (USD)",
    height=320,
    hovermode="x unified",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=10, b=40),
    showlegend=False,
)
# Ensure x-range spans ≥ 14 days so Plotly picks daily (not hourly) tick resolution
_x0 = (values.index[0] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
_x1 = (max(values.index[-1], values.index[0] + pd.Timedelta(days=13)) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
fig.update_xaxes(showgrid=False, range=[_x0, _x1], tickformat="%b %d\n%Y")
fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Weekly log ────────────────────────────────────────────────────────────────
st.subheader("Weekly Log")

log_rows = []
sorted_vals = values.sort_index()

for i, (ts, val) in enumerate(sorted_vals.items()):
    val = float(val)
    prev = float(sorted_vals.iloc[i - 1]) if i > 0 else None
    wk_pnl  = val - prev if prev is not None else None
    wk_pct  = (val / prev - 1) * 100 if prev else None

    # find regime active on or before this date
    regime_on = "—"
    if not regimes.empty:
        past = regimes[regimes.index <= ts]
        if not past.empty:
            regime_on = str(past["regime"].iloc[-1])

    log_rows.append({
        "Date":        ts.date(),
        "Value ($)":   f"${val:,.2f}",
        "Week P&L ($)": f"${wk_pnl:+,.2f}" if wk_pnl is not None else "—",
        "Week P&L (%)": f"{wk_pct:+.2f}%" if wk_pct is not None else "—",
        "Regime":      regime_on,
        "Cum. Return": f"{(val / _INITIAL_CASH - 1) * 100:+.2f}%",
    })

if log_rows:
    log_df = pd.DataFrame(log_rows[::-1])  # newest first

    def _color_regime(val: str) -> str:
        c = _REGIME_COLORS.get(val, "")
        return f"color: {c}" if c else ""

    st.dataframe(
        log_df.style.map(_color_regime, subset=["Regime"]),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── C.2 Position P&L ──────────────────────────────────────────────────────────
st.subheader("Position P&L — This Week")

_probs = load_regime_probs()
if _probs is None:
    st.info("ไม่พบ regime probabilities — รัน weekly job ก่อน")
else:
    from flowmacro.portfolio.allocator import compute_blended_weights as _cbw
    _cur_weights = _cbw(_probs)
    _week_lookback = str(date.today() - timedelta(days=10))

    _pos_rows = []
    for _ticker in sorted(_cur_weights.keys()):
        _w = _cur_weights[_ticker]
        if _w < 0.001:
            continue
        try:
            _px = load_ticker_prices(_ticker, start=_week_lookback)
            _px = _px.dropna()
            if len(_px) >= 2:
                _r = (float(_px.iloc[-1]) / float(_px.iloc[-2]) - 1) * 100
                _contrib = _w * _r
            else:
                _r, _contrib = None, None
        except Exception:
            _r, _contrib = None, None

        _pos_rows.append({
            "Asset":        _ticker,
            "Weight":       f"{_w * 100:.1f}%",
            "Week Return":  f"{_r:+.2f}%" if _r is not None else "—",
            "Contribution": f"{_contrib:+.2f}pp" if _contrib is not None else "—",
        })

    if _pos_rows:
        st.dataframe(pd.DataFrame(_pos_rows), use_container_width=True, hide_index=True)
    st.caption(
        "Contribution = Weight × Week Return  •  "
        "ใช้ราคาล่าสุด 2 จุดจาก yfinance (ประมาณการสัปดาห์ ไม่ใช่ exact Friday-to-Friday)"
    )

# ── C.3 Expected return box ───────────────────────────────────────────────────
st.info(
    "**ผลตอบแทนคาดหวัง** (จาก Walk-Forward backtest V3 — 11 windows, OOS)\n\n"
    "| Scenario       | Sharpe | Expected annual return |\n"
    "|:---------------|:------:|:----------------------:|\n"
    "| Conservative   |  0.7   |  ~10%/ปี               |\n"
    "| Base case      |  1.0   |  ~14%/ปี               |\n"
    "| Good case      |  1.3   |  ~17%/ปี               |\n\n"
    "MaxDD คาดหวัง ≤ 12%  •  ตัวเลขจาก V3 OOS mean Sharpe = 1.06, mean MaxDD = 8.8%"
)

st.caption(
    "Paper portfolio tracks FlowMacro weekly regime signals with $3,000 virtual capital.  "
    "Rebalances every Friday.  Transaction costs: 0.1% round-trip."
)
