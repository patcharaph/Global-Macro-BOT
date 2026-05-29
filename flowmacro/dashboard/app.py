from datetime import date, datetime
import pandas as pd
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


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=300)
def load_latest_regime() -> dict | None:
    try:
        r = _db().table("regime_history").select("*").order("run_date", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_staleness() -> pd.DataFrame:
    try:
        r = _db().table("raw_series").select("series_id, date").execute()
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        latest = df.groupby("series_id")["date"].max().reset_index()
        today = date.today()
        latest["stale_days"] = (
            today - pd.to_datetime(latest["date"]).dt.date
        ).apply(lambda x: x.days)
        latest["status"] = latest["stale_days"].apply(
            lambda d: "✅ OK" if d <= 3 else ("⚠️ Warn" if d <= 30 else "🔴 Stale")
        )
        return latest.rename(columns={
            "series_id": "Indicator",
            "date": "Last Update",
            "stale_days": "Days Stale",
            "status": "Status",
        })[["Indicator", "Last Update", "Days Stale", "Status"]]
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_thb_rate() -> float | None:
    try:
        fx = yf.download("THB=X", period="2d", progress=False, auto_adjust=True)
        return float(fx["Close"].iloc[-1]) if not fx.empty else None
    except Exception:
        return None


# ── Header ──────────────────────────────────────────────────────────────
st.title("📈 FlowMacro — Macro Regime Dashboard")
st.caption(f"Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── Regime ──────────────────────────────────────────────────────────────
latest = load_latest_regime()

if latest:
    regime          = latest["regime"]
    confidence      = float(latest["confidence"])
    growth_score    = float(latest["growth_score"])
    inflation_score = float(latest["inflation_score"])
    run_date        = latest["run_date"]
else:
    regime = confidence = growth_score = inflation_score = run_date = None

icon = _REGIME_ICON.get(regime or "", "❓")
label = regime or "NO DATA — Run weekly job first"
st.subheader(f"{icon}  **{label}**  (as of {run_date or '—'})")

thb_rate = load_thb_rate()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Confidence",      f"{confidence:.1f}%"      if confidence      is not None else "—")
c2.metric("Growth Score",    f"{growth_score:.1f}"     if growth_score    is not None else "—")
c3.metric("Inflation Score", f"{inflation_score:.1f}"  if inflation_score is not None else "—")
c4.metric("THB/USD",         f"{thb_rate:.2f}"         if thb_rate        is not None else "—")

st.divider()

# ── Staleness Flags ──────────────────────────────────────────────────────
st.subheader("Data Staleness")
staleness = load_staleness()
if staleness.empty:
    st.info("No indicator data yet — run the daily job first.")
else:
    st.dataframe(staleness, use_container_width=True, hide_index=True)

st.divider()

# ── Backtest ─────────────────────────────────────────────────────────────
st.subheader("Backtest: FlowMacro vs 60/40 Benchmark")
st.info("Backtest results will appear here after the weekly job runs.")

st.divider()
st.caption("FlowMacro — personal use only, not investment advice")
