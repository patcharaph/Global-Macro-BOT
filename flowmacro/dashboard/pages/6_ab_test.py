"""ML A/B Test — Portfolio A (Rule-only V3) vs Portfolio B (V3 + ML blend 30%)."""
from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from flowmacro.config import settings

st.set_page_config(page_title="A/B Test — FlowMacro", layout="wide")
st.title("ML A/B Test — Portfolio A vs B")
st.caption(
    "A = Rule-based V3 (live, $3,000 real tracking)  |  "
    "B = V3 + ML blend 30% (virtual, same capital notional)  •  "
    "เปรียบเทียบ 26 สัปดาห์ก่อนตัดสิน ML graduation ธ.ค. 2026"
)

_INITIAL_CASH = 3_000.0
_COLOR_A      = "#00ff88"   # neon green — rule-based
_COLOR_B      = "#bf5fff"   # neon purple — ML-blend (distinct from regime colors)
_TARGET_WEEKS = 26


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_portfolio_a() -> pd.Series:
    try:
        from flowmacro.data.store import read_series
        return read_series("paper_total_value", start="2020-01-01").sort_index().dropna()
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=300)
def load_portfolio_b() -> pd.DataFrame:
    try:
        from flowmacro.data.store import read_paper_portfolio_ml
        return read_paper_portfolio_ml()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_ml_shadow() -> pd.DataFrame:
    try:
        from supabase import create_client
        db = create_client(settings.supabase_url, settings.supabase_key)
        rows = (
            db.table("regime_history_ml")
            .select("run_date,ml_regime,rb_regime,agrees,ml_confidence")
            .order("run_date")
            .execute().data
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["run_date"] = pd.to_datetime(df["run_date"])
        return df.set_index("run_date")
    except Exception:
        return pd.DataFrame()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _returns(values: pd.Series) -> pd.Series:
    return values.pct_change().dropna()


def _sharpe(returns: pd.Series) -> float | None:
    if len(returns) < 4 or returns.std() == 0:
        return None
    return float(returns.mean() / returns.std() * (52 ** 0.5))


def _maxdd(values: pd.Series) -> float | None:
    if len(values) < 2:
        return None
    peak = values.expanding().max()
    return float(((values - peak) / peak * 100).min())


# ── Load ──────────────────────────────────────────────────────────────────────
a_values  = load_portfolio_a()
b_df      = load_portfolio_b()
ml_df     = load_ml_shadow()

if a_values.empty:
    st.info("ยังไม่มีข้อมูล Portfolio A — รัน weekly job ก่อน")
    st.stop()

b_values  = b_df["portfolio_value"].dropna() if not b_df.empty else pd.Series(dtype=float)
a_ret     = _returns(a_values)
b_ret     = _returns(b_values)

weeks_a      = max(0, len(a_values) - 1)
weeks_b      = max(0, len(b_values) - 1)
common_idx   = a_ret.index.intersection(b_ret.index) if not b_ret.empty else pd.DatetimeIndex([])
weeks_common = len(common_idx)

a_val    = float(a_values.iloc[-1])
b_val    = float(b_values.iloc[-1]) if not b_values.empty else None
a_total  = (a_val / _INITIAL_CASH - 1) * 100
b_total  = (b_val / _INITIAL_CASH - 1) * 100 if b_val else None

sharpe_a = _sharpe(a_ret)
sharpe_b = _sharpe(b_ret) if weeks_b >= 4 else None
dd_a     = _maxdd(a_values)
dd_b     = _maxdd(b_values) if not b_values.empty else None

# A vs B Agreement — % weeks where both moved in same direction
ab_agreement = None
if weeks_common >= 4:
    a_common = a_ret.loc[common_idx]
    b_common = b_ret.loc[common_idx]
    ab_agreement = float(((a_common > 0) == (b_common > 0)).mean() * 100)

# ── Status banner ─────────────────────────────────────────────────────────────
progress = min(weeks_common, _TARGET_WEEKS)
if weeks_b == 0:
    st.info("Portfolio B ยังไม่มีข้อมูล — จะเริ่มหลัง weekly job รันครั้งแรกพร้อม ML prediction")
elif weeks_common < 4:
    st.warning(f"กำลังสะสมข้อมูล — {weeks_common}/{_TARGET_WEEKS} สัปดาห์ (ต้องการ ≥ 4 สัปดาห์สำหรับ Sharpe)")

st.markdown(
    f"<div style='background:#0d1117;border:1px solid rgba(0,212,255,0.15);border-radius:6px;"
    f"padding:8px 16px;font-family:monospace;font-size:0.85rem;margin-bottom:8px'>"
    f"<span style='color:rgba(255,255,255,0.5)'>Progress: </span>"
    f"<span style='color:#00d4ff'>{progress}/{_TARGET_WEEKS} สัปดาห์</span>"
    f"<span style='color:rgba(255,255,255,0.3)'> — graduation criteria ธ.ค. 2026</span>"
    f"</div>",
    unsafe_allow_html=True,
)

st.divider()

# ── Metric cards ──────────────────────────────────────────────────────────────
st.subheader("Performance Summary")

mc1, mc2, mc3, mc4 = st.columns(4)

mc1.metric(
    "Portfolio A (Rule)",
    f"${a_val:,.2f}",
    delta=f"{a_total:+.2f}% total",
    help="Rule-based V3 softmax — live portfolio",
)
mc2.metric(
    "Portfolio B (ML-blend)",
    f"${b_val:,.2f}" if b_val else "—",
    delta=f"{b_total:+.2f}% total" if b_total is not None else None,
    help="V3 + XGBoost 30% blend — virtual only",
)
mc3.metric(
    "Weeks tracked",
    f"{weeks_common}/{_TARGET_WEEKS}",
    help="สัปดาห์ที่มีข้อมูลทั้งคู่ (ใช้เปรียบเทียบ)",
)
mc4.metric(
    "A vs B Agreement",
    f"{ab_agreement:.0f}%" if ab_agreement is not None else "—",
    help="% สัปดาห์ที่ทั้งคู่เคลื่อนไหวในทิศทางเดียวกัน (same-sign weekly return)",
)

st.divider()

# ── Sharpe + MaxDD ────────────────────────────────────────────────────────────
sc1, sc2, sc3, sc4 = st.columns(4)

sc1.metric(
    "Sharpe A",
    f"{sharpe_a:.2f}" if sharpe_a is not None else "—",
    help="Annualized Sharpe (weekly returns × √52)",
)
sc2.metric(
    "Sharpe B",
    f"{sharpe_b:.2f}" if sharpe_b is not None else "—",
    delta=f"{sharpe_b - sharpe_a:+.2f} vs A" if (sharpe_a and sharpe_b) else None,
)
sc3.metric(
    "MaxDD A",
    f"{dd_a:.1f}%" if dd_a is not None else "—",
    delta_color="inverse",
    help="Maximum drawdown จาก peak",
)
sc4.metric(
    "MaxDD B",
    f"{dd_b:.1f}%" if dd_b is not None else "—",
    delta=f"{dd_b - dd_a:+.1f}% vs A" if (dd_a is not None and dd_b is not None) else None,
    delta_color="inverse",
)

st.divider()

# ── Equity curves ─────────────────────────────────────────────────────────────
st.subheader("Equity Curves")

fig = go.Figure()

fig.add_hline(
    y=_INITIAL_CASH,
    line_dash="dot",
    line_color="rgba(255,255,255,0.2)",
    annotation_text=f"Start ${_INITIAL_CASH:,.0f}",
    annotation_font=dict(color="rgba(255,255,255,0.4)", size=9),
    annotation_position="bottom right",
)

fig.add_trace(go.Scatter(
    x=[ts.strftime("%Y-%m-%d") for ts in a_values.index],
    y=a_values.values,
    name="A: Rule-only V3",
    mode="lines+markers",
    line=dict(color=_COLOR_A, width=2.5),
    marker=dict(size=6),
    hovertemplate="<b>%{x}</b><br>A: $%{y:,.2f}<extra></extra>",
))

if not b_values.empty:
    fig.add_trace(go.Scatter(
        x=[ts.strftime("%Y-%m-%d") for ts in b_values.index],
        y=b_values.values,
        name="B: ML-blend 30%",
        mode="lines+markers",
        line=dict(color=_COLOR_B, width=2.5, dash="dash"),
        marker=dict(size=6, symbol="diamond"),
        hovertemplate="<b>%{x}</b><br>B: $%{y:,.2f}<extra></extra>",
    ))

fig.update_layout(
    yaxis_title="Portfolio Value (USD)",
    height=360,
    hovermode="x unified",
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(t=10, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                font=dict(family="monospace", size=11)),
)
_x0 = (a_values.index[0] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
_x1 = (a_values.index[-1] + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
fig.update_xaxes(showgrid=False, range=[_x0, _x1], tickformat="%b %d\n%Y",
                 color="rgba(0,212,255,0.6)")
fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.07)",
                 color="rgba(0,212,255,0.6)")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.divider()

# ── ML Regime in Portfolio B ──────────────────────────────────────────────────
if not b_df.empty and "ml_regime" in b_df.columns:
    st.subheader("ML Regime — Portfolio B week-by-week")
    _REGIME_COLOR = {
        "GOLDILOCKS":    "#00ff88",
        "REFLATION":     "#ffcc00",
        "STAGFLATION":   "#ff4466",
        "DEFLATION":     "#00d4ff",
        "TRANSITIONING": "#8888aa",
    }
    _ml_rows = b_df[["ml_regime", "ml_confidence", "period_return"]].copy()
    _ml_rows = _ml_rows.reset_index()
    _ml_rows["date"] = _ml_rows["date"].dt.strftime("%Y-%m-%d")
    _ml_rows["period_return"] = (_ml_rows["period_return"] * 100).round(2)
    _ml_rows.columns = ["Date", "ML Regime", "ML Confidence", "B Week Return (%)"]

    def _color_regime(val: str) -> str:
        c = _REGIME_COLOR.get(val, "")
        return f"color: {c}; font-weight: bold" if c else ""

    st.dataframe(
        _ml_rows[::-1].style.map(_color_regime, subset=["ML Regime"]),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Weekly log — side by side ─────────────────────────────────────────────────
st.subheader("Weekly Log — A vs B")

log_rows = []
all_dates = a_values.index.union(b_values.index if not b_values.empty else pd.DatetimeIndex([]))

for ts in sorted(all_dates):
    a_v = float(a_values.loc[ts]) if ts in a_values.index else None
    b_v = float(b_values.loc[ts]) if (not b_values.empty and ts in b_values.index) else None

    # week returns
    a_pos = a_values.index.get_loc(ts) if ts in a_values.index else None
    b_pos = b_values.index.get_loc(ts) if (not b_values.empty and ts in b_values.index) else None

    a_wret = (a_v / float(a_values.iloc[a_pos - 1]) - 1) * 100 if (a_pos and a_pos > 0 and a_v) else None
    b_wret = (b_v / float(b_values.iloc[b_pos - 1]) - 1) * 100 if (b_pos and b_pos > 0 and b_v) else None

    log_rows.append({
        "Date":        ts.strftime("%Y-%m-%d"),
        "A Value ($)": f"${a_v:,.2f}" if a_v else "—",
        "A Week (%)":  f"{a_wret:+.2f}%" if a_wret is not None else "—",
        "B Value ($)": f"${b_v:,.2f}" if b_v else "—",
        "B Week (%)":  f"{b_wret:+.2f}%" if b_wret is not None else "—",
        "Δ A-B ($)":   f"${a_v - b_v:+.2f}" if (a_v and b_v) else "—",
    })

if log_rows:
    st.dataframe(
        pd.DataFrame(log_rows[::-1]),
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "Portfolio A = live rule-based V3 | Portfolio B = virtual ML-blend 30%  •  "
    "ทั้งคู่เริ่มต้น $3,000 เพื่อเปรียบเทียบอย่างยุติธรรม  •  "
    "ผล 26 สัปดาห์จะประกอบการตัดสิน ML graduation criteria ธ.ค. 2026"
)
