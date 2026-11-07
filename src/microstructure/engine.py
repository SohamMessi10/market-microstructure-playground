"""The matching engine: applies price-time priority to incoming limit orders.

    submit(BUY, 102, 10)
      while the order has quantity left and crosses the book:
          take the oldest order at the best opposite price
          trade min(both remaining) at the RESTING order's price
      rest whatever is left at the order's limit price

    cancel(order_id)
      remove what is still resting; what already traded stays traded

The engine owns every number that decides priority: order ids, trade ids, and arrival
numbers all come from counters here, never from the caller or a clock. The same
sequence of calls therefore always produces the same trades.

It also keeps a record of every order it has accepted, so each one can be accounted
for: quantity = filled + resting + cancelled.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from microstructure.book import Book, InvariantError, find_problems
from microstructure.models import Order, OrderError, Side, Trade, check_price, check_quantity

MAX_TRADER_LENGTH = 50


class Status(Enum):
    FILLED = "filled"                      # traded completely on arrival
    PARTIALLY_FILLED = "partially_filled"  # traded some, the rest is resting
    RESTING = "resting"                    # traded nothing, all of it is resting


class OrderState(Enum):
    OPEN = "open"            # some quantity is resting in the book
    FILLED = "filled"        # all of it traded
    CANCELLED = "cancelled"  # the rest was cancelled (some may have traded first)


@dataclass(slots=True)
class OrderRecord:
    """Everything that happened to one order. quantity = filled + resting + cancelled."""

    order_id: int
    side: Side
    price: int
    quantity: int
    trader: str = ""
    filled: int = 0
    cancelled: int = 0

    @property
    def resting(self) -> int:
        return self.quantity - self.filled - self.cancelled

    @property
    def state(self) -> OrderState:
        if self.cancelled:
            return OrderState.CANCELLED
        return OrderState.FILLED if self.filled == self.quantity else OrderState.OPEN


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


@dataclass(frozen=True, slots=True)
class CancelResult:
    """A cancel either removes the resting quantity or is refused with a reason.

    Refusals are results, not exceptions: in a replay, a cancel that arrives after its
    order has already traded is normal, and the replay should carry on.
    """

    order_id: int
    cancelled: int        # quantity removed from the book; 0 when refused
    reason: str = ""      # why it was refused; empty when it succeeded

    @property
    def ok(self) -> bool:
        return not self.reason


class MatchingEngine:
    """One instrument's order book plus the rules for trading against it."""

    def __init__(self) -> None:
        self.book = Book()
        self.trades: list[Trade] = []  # every trade, in the order it happened
        self._orders: dict[int, OrderRecord] = {}
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
        record = self._orders[order_id] = OrderRecord(order_id, side, price, quantity, trader)

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
            self._orders[resting.order_id].filled += quantity_traded
            incoming.remaining -= quantity_traded
            trades.append(trade)

        record.filled = quantity - incoming.remaining
        if incoming.remaining:
            self.book.insert(incoming)
        self.trades.extend(trades)

        if incoming.remaining == 0:
            status = Status.FILLED
        elif record.filled:
            status = Status.PARTIALLY_FILLED
        else:
            status = Status.RESTING
        return SubmitResult(order_id, status, tuple(trades), record.filled, incoming.remaining)

    def cancel(self, order_id: int) -> CancelResult:
        """Cancel whatever is still resting of an order."""
        if isinstance(order_id, bool) or not isinstance(order_id, int):
            raise OrderError(f"order id must be a whole number, got {order_id!r}")
        record = self._orders.get(order_id)
        if record is None:
            return CancelResult(order_id, 0, f"there is no order {order_id}")
        if record.state is OrderState.FILLED:
            return CancelResult(order_id, 0, f"order {order_id} already traded in full")
        if record.state is OrderState.CANCELLED:
            return CancelResult(order_id, 0, f"order {order_id} was already cancelled")
        removed = self.book.remove(order_id).remaining
        record.cancelled = removed
        return CancelResult(order_id, removed)

    def order(self, order_id: int) -> OrderRecord | None:
        """A copy of one order's record, or None if there was never such an order."""
        record = self._orders.get(order_id)
        return dataclasses.replace(record) if record else None

    def orders(self) -> list[OrderRecord]:
        """Copies of every order's record, oldest first."""
        return [dataclasses.replace(r) for r in self._orders.values()]

    def find_problems(self) -> list[str]:
        """The book's own checks, plus whether every order's quantity is accounted for."""
        problems = find_problems(self.book)
        traded = Counter()
        for trade in self.trades:
            traded[trade.buy_order_id] += trade.quantity
            traded[trade.sell_order_id] += trade.quantity
            for order_id, side in ((trade.buy_order_id, Side.BUY), (trade.sell_order_id, Side.SELL)):
                record = self._orders.get(order_id)
                if record is None or record.side is not side:
                    problems.append(f"trade {trade.trade_id} names order {order_id} as a {side.value}er")
        for record in self._orders.values():
            name = f"order {record.order_id}"
            if record.filled != traded[record.order_id]:
                problems.append(f"{name} records {record.filled} filled, but its trades add up to "
                                f"{traded[record.order_id]}")
            if not 0 <= record.resting <= record.quantity or record.cancelled < 0:
                problems.append(f"{name} doesn't add up: {record.quantity} = {record.filled} filled "
                                f"+ {record.cancelled} cancelled + {record.resting} resting")
            in_book = self.book.get(record.order_id)
            if record.resting != (in_book.remaining if in_book else 0):
                problems.append(f"{name} should have {record.resting} resting, but the book has "
                                f"{in_book.remaining if in_book else 0}")
        if len(self.book) != sum(1 for r in self._orders.values() if r.resting):
            problems.append("the book holds orders the engine has no open record of")
        return problems

    def check(self) -> None:
        """Raise InvariantError listing every problem, if there are any."""
        problems = self.find_problems()
        if problems:
            raise InvariantError("matching engine is inconsistent:\n- " + "\n- ".join(problems))
