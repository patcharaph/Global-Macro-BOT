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


_SERIES_SOURCES = {
    "SPY":          "yfinance",
    "T10Y2Y":       "FRED",
    "BAMLH0A0HYM2": "FRED",
    "T5YIE":        "FRED",
    "USSLIND":      "FRED",
    "regime_code":  "pipeline",
}

_STALE_WARN = {"yfinance": 3, "FRED": 7, "pipeline": 7}


@st.cache_data(ttl=300)
def load_source_health() -> pd.DataFrame:
    try:
        r = _db().table("raw_series").select("series_id, date").execute()
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        latest = df.groupby("series_id")["date"].max()
        today = date.today()
        rows = []
        for series_id, source in _SERIES_SOURCES.items():
            last = latest.get(series_id)
            if last is None:
                rows.append({"Source": source, "Series": series_id, "Last Update": "—", "Days Stale": "—", "Status": "❌ No data"})
                continue
            stale_days = (today - pd.to_datetime(last).date()).days
            threshold = _STALE_WARN.get(source, 7)
            status = "✅ OK" if stale_days <= threshold else ("⚠️ Warn" if stale_days <= threshold * 3 else "🔴 Stale")
            rows.append({"Source": source, "Series": series_id, "Last Update": str(last), "Days Stale": stale_days, "Status": status})
        return pd.DataFrame(rows)
    except Exception as exc:
        st.error(f"Cannot connect to Supabase: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_staleness_all() -> pd.DataFrame:
    try:
        r = _db().table("raw_series").select("series_id, date").execute()
        if not r.data:
            return pd.DataFrame()
        df = pd.DataFrame(r.data)
        latest = df.groupby("series_id")["date"].max().reset_index()
        today = date.today()
        latest["days_stale"] = (today - pd.to_datetime(latest["date"]).dt.date).apply(lambda x: x.days)
        latest["status"] = latest["days_stale"].apply(
            lambda d: "✅" if d <= 3 else ("⚠️" if d <= 30 else "🔴")
        )
        return latest.sort_values("days_stale", ascending=False).rename(columns={
            "series_id": "Series", "date": "Last Update", "days_stale": "Days Stale", "status": "Status"
        })[["Series", "Last Update", "Days Stale", "Status"]]
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
