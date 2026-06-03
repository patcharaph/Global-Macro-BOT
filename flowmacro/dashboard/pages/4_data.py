"""Raw data explorer — browse any series stored in Supabase."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client
from flowmacro.config import settings

st.set_page_config(page_title="Data — FlowMacro", layout="wide")
st.title("Raw Data Explorer")


def _db():
    return create_client(settings.supabase_url, settings.supabase_key)


@st.cache_data(ttl=300)
def list_series() -> list[str]:
    try:
        rows = _db().table("raw_series").select("series_id").execute().data
        return sorted({r["series_id"] for r in rows})
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_series(series_id: str) -> pd.Series:
    try:
        from flowmacro.data.store import read_series
        return read_series(series_id, start="2000-01-01")
    except Exception:
        return pd.Series(dtype=float)


series_ids = list_series()
if not series_ids:
    st.warning("ไม่มีข้อมูลใน Supabase — รัน daily job ก่อน")
    st.stop()

selected = st.selectbox("Series", series_ids)
s = load_series(selected)

if s.empty:
    st.info(f"ไม่มีข้อมูลสำหรับ {selected}")
    st.stop()

# ── Chart ─────────────────────────────────────────────────────────────────────
fig = go.Figure(go.Scatter(
    x=s.index, y=s.values,
    mode="lines",
    line=dict(color="#2ecc71", width=1.5),
    hovertemplate="%{x|%Y-%m-%d}: %{y:.4f}<extra></extra>",
))
fig.update_layout(
    height=350,
    margin=dict(t=10, b=40, l=50, r=10),
    xaxis_title="",
    yaxis_title=selected,
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
)
fig.update_xaxes(showgrid=False)
fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.08)")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ── Stats + Download ──────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Rows",    f"{len(s):,}")
c2.metric("From",    str(s.index.min().date()))
c3.metric("To",      str(s.index.max().date()))
c4.metric("Min",     f"{s.min():.4f}")
c5.metric("Max",     f"{s.max():.4f}")

csv = s.rename("value").reset_index().rename(columns={"index": "date"}).to_csv(index=False)
st.download_button(
    label="Download CSV",
    data=csv,
    file_name=f"{selected}.csv",
    mime="text/csv",
)

st.divider()

# ── Table ─────────────────────────────────────────────────────────────────────
df = s.rename("value").reset_index().rename(columns={"index": "date"})
df["date"] = df["date"].dt.strftime("%Y-%m-%d")
st.dataframe(df.iloc[::-1].reset_index(drop=True), use_container_width=True, hide_index=True)
