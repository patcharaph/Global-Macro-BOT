import sys
from loguru import logger
from flowmacro.data.sources.prices import fetch_prices
from flowmacro.data.store import upsert_series

_PRICE_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "FXI", "EWJ",
    "TLT", "IEF", "HYG",
    "GLD", "USO", "DBC", "SLV",
    "UUP", "FXE", "FXY",
    "HG=F", "GC=F",  # for copper_gold derived indicator
    "THB=X",         # THB/USD rate for dashboard
]

_START = "2005-01-01"


def run() -> None:
    logger.info("Daily job: start")
    try:
        prices, stale = fetch_prices(_PRICE_TICKERS, start=_START)

        for ticker in _PRICE_TICKERS:
            if ticker in prices.columns:
                upsert_series(ticker, prices[ticker].dropna())

        # Derived indicators — dropna ก่อน rolling เพื่อหลีกเลี่ยง NaN จาก multi-ticker date alignment
        hg = prices["HG=F"].dropna()
        gc = prices["GC=F"].dropna()
        upsert_series("copper_gold", (hg / gc).dropna())

        spy = prices["SPY"].dropna()
        upsert_series("spy_200ma", ((spy / spy.rolling(200).mean()) - 1).mul(100).dropna())

        uup = prices["UUP"].dropna()
        upsert_series("dxy_trend", ((uup / uup.rolling(20).mean()) - 1).mul(100).dropna())

        # Alert if any key series is stale > 3 days
        stale_warn = {k: v for k, v in stale.items() if v > 3 and k in _PRICE_TICKERS[:17]}
        if stale_warn:
            from flowmacro.alerts.gmail import send_alert
            send_alert("Data Staleness Warning", f"Stale series (>3 days):\n{stale_warn}")

        logger.info("Daily job: done")

    except Exception as exc:
        logger.error(f"Daily job failed: {exc}")
        try:
            from flowmacro.alerts.gmail import send_alert
            send_alert("Daily Job FAILED", str(exc))
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    run()
