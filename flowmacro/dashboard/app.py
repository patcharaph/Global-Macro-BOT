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


_REGIME_DECODE = {1: "GOLDILOCKS", 2: "REFLATION", 3: "STAGFLATION", 4: "DEFLATION", 0: "TRANSITIONING"}


@st.cache_data(ttl=300)
def load_latest_regime() -> dict | None:
    try:
        db = _db()
        def _latest(sid: str) -> float | None:
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


@st.cache_data(ttl=300)
def load_staleness() -> pd.DataFrame:
    try:
        from flowmacro.regime.indicators import INDICATORS
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
            status = "✅ OK" if stale <= 3 else ("⚠️ Warn" if stale <= 30 else "🔴 Stale")
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
