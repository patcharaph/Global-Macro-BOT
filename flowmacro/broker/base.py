"""
Abstract broker interface for FlowMacro.

Phase 2 scope: interface definition only — no live broker connected.
Live trading (IBKR) activates when capital >= $10,000 USD.

Implementors: swap in a concrete class (e.g. IBKRBroker) without changing
any upstream portfolio or scheduler code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Order:
    ticker: str
    qty: float          # shares / units (negative = short)
    side: str           # "buy" or "sell"
    order_type: str = "market"
    limit_price: float | None = None
    notes: str = ""


@dataclass
class Position:
    ticker: str
    qty: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float = 0.0


@dataclass
class AccountSnapshot:
    total_value: float
    cash: float
    positions: list[Position] = field(default_factory=list)
    as_of: datetime = field(default_factory=datetime.utcnow)


class BrokerBase(ABC):
    """Minimal broker interface. All methods must be implemented by subclasses."""

    @abstractmethod
    def place_order(self, order: Order) -> str:
        """Submit an order. Returns broker-assigned order ID."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order. Returns True if cancelled."""

    @abstractmethod
    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count cancelled."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all currently held positions."""

    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        """Return full account snapshot (cash + positions + total value)."""


class PaperBroker(BrokerBase):
    """In-memory paper broker for testing and simulation.

    Fills all orders immediately at the provided price (no slippage model).
    Not persisted — state resets on process restart.
    """

    def __init__(self, initial_cash: float = 3_000.0) -> None:
        self._cash = initial_cash
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._order_seq = 0

    def place_order(self, order: Order) -> str:
        self._order_seq += 1
        oid = f"PAPER-{self._order_seq:04d}"
        self._orders[oid] = order
        # Immediate fill at limit_price if set, otherwise at cost=0 (caller handles valuation)
        fill_price = order.limit_price or 0.0
        cost = fill_price * abs(order.qty)
        if order.side == "buy":
            self._cash -= cost
            pos = self._positions.get(order.ticker)
            if pos:
                new_qty = pos.qty + order.qty
                new_cost = (pos.avg_cost * pos.qty + fill_price * order.qty) / new_qty if new_qty else 0
                self._positions[order.ticker] = Position(order.ticker, new_qty, new_cost, new_qty * fill_price)
            else:
                self._positions[order.ticker] = Position(order.ticker, order.qty, fill_price, cost)
        else:
            self._cash += cost
            pos = self._positions.get(order.ticker)
            if pos:
                new_qty = pos.qty - order.qty
                self._positions[order.ticker] = Position(order.ticker, new_qty, pos.avg_cost, new_qty * fill_price)
        return oid

    def cancel_order(self, order_id: str) -> bool:
        return bool(self._orders.pop(order_id, None))

    def cancel_all_orders(self) -> int:
        n = len(self._orders)
        self._orders.clear()
        return n

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.qty != 0]

    def get_account(self) -> AccountSnapshot:
        positions = self.get_positions()
        invested = sum(p.market_value for p in positions)
        return AccountSnapshot(
            total_value=self._cash + invested,
            cash=self._cash,
            positions=positions,
        )
