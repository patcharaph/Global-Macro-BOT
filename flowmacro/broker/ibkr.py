"""
IBKR live broker implementation using ib_insync.

Prerequisites:
  1. IB Gateway (or TWS) running and API enabled
  2. pip install ib_insync
  3. Set env vars: IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID

Port defaults:
  IB Gateway paper:  4002
  IB Gateway live:   4001
  TWS paper:         7497
  TWS live:          7496

Usage:
  broker = IBKRBroker.connect()
  try:
      snapshot = broker.get_account()
      order_id = broker.place_order(Order("SPY", 10, "buy"))
  finally:
      broker.disconnect()
"""
import os
import time
from datetime import datetime
from loguru import logger

from flowmacro.broker.base import BrokerBase, Order, Position, AccountSnapshot

_DEFAULT_HOST      = "127.0.0.1"
_DEFAULT_PORT      = 4001
_DEFAULT_CLIENT_ID = 10
_CONNECT_TIMEOUT   = 10  # seconds
_ORDER_WAIT        = 3   # seconds to wait for fill confirmation


class IBKRBroker(BrokerBase):
    """Live IBKR broker via ib_insync. Call connect() then disconnect() when done."""

    def __init__(self, ib) -> None:
        self._ib = ib

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def connect(
        cls,
        host:      str | None = None,
        port:      int | None = None,
        client_id: int | None = None,
        readonly:  bool = False,
    ) -> "IBKRBroker":
        """Connect to IB Gateway / TWS and return a ready broker instance."""
        from ib_insync import IB, util
        util.startLoop()  # safe to call multiple times; no-op if loop already running

        h  = host      or os.getenv("IBKR_HOST",      _DEFAULT_HOST)
        p  = int(port  or os.getenv("IBKR_PORT",      str(_DEFAULT_PORT)))
        cid = int(client_id or os.getenv("IBKR_CLIENT_ID", str(_DEFAULT_CLIENT_ID)))

        ib = IB()
        ib.connect(h, p, clientId=cid, readonly=readonly, timeout=_CONNECT_TIMEOUT)
        logger.info(f"IBKR connected: {h}:{p}  clientId={cid}  readonly={readonly}")
        return cls(ib)

    def disconnect(self) -> None:
        self._ib.disconnect()
        logger.info("IBKR disconnected")

    # ── BrokerBase implementation ─────────────────────────────────────────────

    def place_order(self, order: Order) -> str:
        from ib_insync import Stock, MarketOrder, LimitOrder

        contract = Stock(order.ticker, "SMART", "USD")
        qty      = max(1, round(abs(order.qty)))

        if order.order_type == "limit" and order.limit_price:
            ib_order = LimitOrder(order.side.upper(), qty, order.limit_price)
        else:
            ib_order = MarketOrder(order.side.upper(), qty)

        trade = self._ib.placeOrder(contract, ib_order)
        logger.info(
            f"Order submitted: {order.side.upper()} {qty} {order.ticker}  "
            f"type={order.order_type}  orderId={trade.order.orderId}"
        )

        # Wait briefly for acknowledgement (not full fill — don't block weekly job)
        self._ib.sleep(_ORDER_WAIT)
        status = trade.orderStatus.status
        logger.info(f"Order {trade.order.orderId} status: {status}")

        return str(trade.order.orderId)

    def cancel_order(self, order_id: str) -> bool:
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                logger.info(f"Cancelled order {order_id}")
                return True
        logger.warning(f"Order {order_id} not found in open trades")
        return False

    def cancel_all_orders(self) -> int:
        open_trades = self._ib.openTrades()
        for trade in open_trades:
            self._ib.cancelOrder(trade.order)
        n = len(open_trades)
        logger.info(f"Cancelled {n} open orders")
        return n

    def get_positions(self) -> list[Position]:
        positions = []
        for pos in self._ib.positions():
            contract   = pos.contract
            mkt_value  = pos.position * self._last_price(contract)
            avg_cost   = float(pos.avgCost) if pos.avgCost else 0.0
            positions.append(Position(
                ticker         = contract.symbol,
                qty            = float(pos.position),
                avg_cost       = avg_cost,
                market_value   = mkt_value,
                unrealized_pnl = mkt_value - avg_cost * float(pos.position),
            ))
        return positions

    def get_account(self) -> AccountSnapshot:
        vals  = {v.tag: v.value for v in self._ib.accountValues() if v.currency == "USD"}
        cash  = float(vals.get("CashBalance", 0.0))
        total = float(vals.get("NetLiquidation", 0.0)) or (cash + sum(
            p.market_value for p in self.get_positions()
        ))
        return AccountSnapshot(
            total_value = total,
            cash        = cash,
            positions   = self.get_positions(),
            as_of       = datetime.utcnow(),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _last_price(self, contract) -> float:
        """Request last price for contract; returns 0.0 on failure."""
        try:
            self._ib.qualifyContracts(contract)
            ticker = self._ib.reqMktData(contract, "", False, False)
            self._ib.sleep(1)
            price = ticker.last or ticker.close or ticker.bid or 0.0
            self._ib.cancelMktData(contract)
            return float(price) if price else 0.0
        except Exception as exc:
            logger.warning(f"Price fetch failed for {contract.symbol}: {exc}")
            return 0.0
