"""System health page — pipeline run history + data source status."""
from datetime import date
import pandas as pd
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Health — FlowMacro", layout="wide")
st.title("System Health")


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


_STALE_WARN = {"yfinance": 3, "FRED": 7, "pipeline": 7}


def _build_series_sources() -> dict[str, str]:
    from flowmacro.regime.indicators import INDICATORS
    sources = {}
    for ind in INDICATORS:
        sources[ind.series_id] = "FRED" if ind.source == "fred" else "yfinance"
    sources.update({
        "copper_gold": "yfinance", "spy_200ma": "yfinance", "dxy_trend": "yfinance",
        "cpi_yoy": "FRED", "SPY": "yfinance", "THB=X": "yfinance",
        "regime_code": "pipeline", "regime_confidence": "pipeline",
        "growth_score": "pipeline", "inflation_score": "pipeline",
    })
    return sources


@st.cache_data(ttl=300)
def load_source_health() -> pd.DataFrame:
    try:
        _SERIES_SOURCES = _build_series_sources()
        db = _db()
        today = date.today()
        rows = []
        for series_id, source in _SERIES_SOURCES.items():
            r = db.table("raw_series").select("date").eq("series_id", series_id) \
                  .order("date", desc=True).limit(1).execute()
            if not r.data:
                rows.append({"Source": source, "Series": series_id, "Last Update": "—", "Days Stale": "—", "Status": "❌ No data"})
                continue
            stale_days = (today - pd.to_datetime(r.data[0]["date"]).date()).days
            threshold = _STALE_WARN.get(source, 7)
            status = "✅ OK" if stale_days <= threshold else ("⚠️ Warn" if stale_days <= threshold * 3 else "🔴 Stale")
            rows.append({"Source": source, "Series": series_id, "Last Update": r.data[0]["date"], "Days Stale": stale_days, "Status": status})
        return pd.DataFrame(rows)
    except Exception as exc:
        st.error(f"Cannot connect to Supabase: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_staleness_all() -> pd.DataFrame:
    try:
        from flowmacro.regime.indicators import INDICATORS
        db = _db()
        today = date.today()
        rows = []
        series_ids = list(dict.fromkeys(
            [i.series_id for i in INDICATORS] + [
                "copper_gold", "spy_200ma", "dxy_trend", "cpi_yoy",
                "regime_code", "regime_confidence", "growth_score", "inflation_score",
            ]
        ))
        from flowmacro.regime.indicators import stale_threshold
        for sid in series_ids:
            r = db.table("raw_series").select("date").eq("series_id", sid) \
                  .order("date", desc=True).limit(1).execute()
            if not r.data:
                continue
            last_date = pd.to_datetime(r.data[0]["date"]).date()
            stale = (today - last_date).days
            threshold = stale_threshold(sid)
            status = "✅" if stale <= threshold else ("⚠️" if stale <= threshold * 2 else "🔴")
            rows.append({"Series": sid, "Last Update": str(last_date), "Days Stale": stale,
                         "Status": status})
        return pd.DataFrame(rows).sort_values("Days Stale", ascending=False)
    except Exception:
        return pd.DataFrame()


# ── Data source health ────────────────────────────────────────────────────────
st.subheader("Data Source Status")
health = load_source_health()
if health.empty:
    st.warning("ไม่มีข้อมูลใน Supabase — รัน daily job ก่อน")
else:
    st.dataframe(health, use_container_width=True, hide_index=True)

st.divider()

# ── Full staleness table ──────────────────────────────────────────────────────
st.subheader("All Series Staleness")
staleness = load_staleness_all()
if not staleness.empty:
    st.dataframe(staleness, use_container_width=True, hide_index=True)

st.caption(f"Auto-refreshes every 5 minutes  |  Last page load: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
