"""The matching engine: applies price-time priority to incoming limit orders.

    submit(BUY, 102, 10)
      while the order has quantity left and crosses the book:
          take the oldest order at the best opposite price
          trade min(both remaining) at the RESTING order's price
      rest whatever is left at the order's limit price

The engine owns every number that decides priority: order ids, trade ids, and arrival
numbers all come from counters here, never from the caller or a clock. The same
sequence of calls therefore always produces the same trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from microstructure.book import Book
from microstructure.models import Order, OrderError, Side, Trade, check_price, check_quantity

MAX_TRADER_LENGTH = 50


class Status(Enum):
    FILLED = "filled"                      # traded completely on arrival
    PARTIALLY_FILLED = "partially_filled"  # traded some, the rest is resting
    RESTING = "resting"                    # traded nothing, all of it is resting


@dataclass(frozen=True, slots=True)
class SubmitResult:
    order_id: int
    status: Status
    trades: tuple[Trade, ...]
    filled: int   # quantity traded on arrival
    resting: int  # quantity left in the book

    @property
    def average_price(self) -> float | None:
        """Volume-weighted price of this order's trades, in ticks."""
        if not self.trades:
            return None
        return sum(t.price * t.quantity for t in self.trades) / self.filled


class MatchingEngine:
    """One instrument's order book plus the rules for trading against it."""

    def __init__(self) -> None:
        self.book = Book()
        self.trades: list[Trade] = []  # every trade, in the order it happened
        self._next_order_id = 1
        self._next_trade_id = 1

    def submit(self, side: Side, price: int, quantity: int, trader: str = "") -> SubmitResult:
        """Submit a limit order: buy at most, or sell at least, `price` ticks."""
        if not isinstance(side, Side):
            raise OrderError(f"side must be Side.BUY or Side.SELL, got {side!r}")
        check_price(price)
        check_quantity(quantity)
        if not isinstance(trader, str) or len(trader) > MAX_TRADER_LENGTH:
            raise OrderError(f"trader must be text of at most {MAX_TRADER_LENGTH} characters")

        # Ids double as arrival numbers: one counter, so they can't disagree.
        order_id = self._next_order_id
        self._next_order_id += 1
        incoming = Order(order_id, side, price, quantity, quantity, seq=order_id, trader=trader)

        trades = []
        opposite = self.book.side(side.opposite)
        while incoming.remaining and self.book.crosses(side, price):
            resting = opposite.level(opposite.best()).first()  # best price, then oldest
            quantity_traded = min(incoming.remaining, resting.remaining)
            trade = Trade(
                trade_id=self._next_trade_id,
                price=resting.price,  # the resting order set the price
                quantity=quantity_traded,
                buy_order_id=incoming.order_id if side is Side.BUY else resting.order_id,
                sell_order_id=resting.order_id if side is Side.BUY else incoming.order_id,
                aggressor=side,
            )
            self._next_trade_id += 1
            self.book.fill(resting.order_id, quantity_traded)
            incoming.remaining -= quantity_traded
            trades.append(trade)

        if incoming.remaining:
            self.book.insert(incoming)
        self.trades.extend(trades)

        filled = quantity - incoming.remaining
        if incoming.remaining == 0:
            status = Status.FILLED
        elif filled:
            status = Status.PARTIALLY_FILLED
        else:
            status = Status.RESTING
        return SubmitResult(order_id, status, tuple(trades), filled, incoming.remaining)
