"""Weekly allocation table + week-over-week diff for the email alert.

Kept ASCII-only (no unicode arrows) — a prior bug (commit 0f6d459) showed that
strings containing unicode symbols crash when they end up in a Windows console
via logger.info/print (cp874 codepage). The email itself is UTF-8 safe, but any
string built here may also get logged, so we stay ASCII everywhere.
"""

ASSET_LABELS: dict[str, str] = {
    "SPY":     "SPY  S&P 500",
    "QQQ":     "QQQ  Nasdaq 100",
    "IWM":     "IWM  Small Cap",
    "EFA":     "EFA  Developed ex-US",
    "EEM":     "EEM  EM Stocks",
    "BTC-USD": "BTC  Bitcoin",
    "GLD":     "GLD  Gold",
    "SLV":     "SLV  Silver",
    "DBC":     "DBC  Commodities",
    "UUP":     "UUP  US Dollar",
    "TLT":     "TLT  Long Treasury",
    "IEF":     "IEF  7-10Y Treasury",
    "SHY":     "SHY  T-Bill",
    "CASH":    "CASH",
}

AB_THRESHOLD  = 0.05    # show Port A and Port B separately if any asset differs by >= 5pp
WOW_THRESHOLD = 0.005   # week-over-week change smaller than this is treated as "no change"


def _with_cash(weights: dict[str, float]) -> dict[str, float]:
    """Add a synthetic CASH line so the displayed weights sum to 100%."""
    invested = sum(weights.values())
    out = dict(weights)
    out["CASH"] = max(0.0, 1.0 - invested)
    return out


def _portfolios_differ(alloc_a: dict[str, float], alloc_b: dict[str, float]) -> bool:
    tickers = set(alloc_a) | set(alloc_b)
    return any(abs(alloc_a.get(t, 0) - alloc_b.get(t, 0)) >= AB_THRESHOLD for t in tickers)


def _format_single_port(
    label: str,
    current: dict[str, float],
    previous: dict[str, float] | None,
) -> str:
    """Format one portfolio's allocation, with a week-over-week diff if `previous` is given."""
    current  = _with_cash(current)
    previous = _with_cash(previous) if previous else None

    tickers = sorted(
        set(current) | (set(previous) if previous else set()),
        key=lambda t: current.get(t, 0),
        reverse=True,
    )

    lines = [f"[{label}]"]
    for t in tickers:
        cur  = current.get(t, 0.0)
        prev = previous.get(t, 0.0) if previous is not None else None
        name = ASSET_LABELS.get(t, t)

        if cur < WOW_THRESHOLD and (prev is None or prev < WOW_THRESHOLD):
            continue

        if prev is None or abs(cur - prev) < WOW_THRESHOLD:
            lines.append(f"  {name:<20} {cur*100:5.1f}%")
        elif cur > prev:
            lines.append(f"  {name:<20} {prev*100:4.1f}% -> {cur*100:.1f}%  (+{(cur-prev)*100:.1f}%)")
        else:
            lines.append(f"  {name:<20} {prev*100:4.1f}% -> {cur*100:.1f}%  (-{(prev-cur)*100:.1f}%)")

    return "\n".join(lines)


def format_allocation_section(
    current_a: dict[str, float],
    prev_a: dict[str, float] | None,
    current_b: dict[str, float] | None = None,
    prev_b: dict[str, float] | None = None,
) -> str:
    """Build the allocation section of the weekly email.

    current_a/prev_a: Port A (rule-based, live). current_b/prev_b: Port B
    (ML-blend, paper only) — pass None when the ML shadow prediction failed
    this week, in which case only Port A is shown.
    """
    if current_b is None:
        return "Allocation:\n" + _format_single_port("Port A - Rule-based", current_a, prev_a)

    if _portfolios_differ(current_a, current_b):
        section_a = _format_single_port("Port A - Rule-based",       current_a, prev_a)
        section_b = _format_single_port("Port B - ML-blend (paper)", current_b, prev_b)
        return f"Allocation (A != B, diff >= {AB_THRESHOLD*100:.0f}pp):\n{section_a}\n\n{section_b}"

    section = _format_single_port("Port A = Port B", current_a, prev_a)
    return f"Allocation:\n{section}"
