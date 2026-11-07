"""The order book: resting buy and sell orders, grouped by price, in arrival order.

The book is a data structure, not the rules. It stores orders and answers questions
(best bid, best ask, depth), and it refuses an insert that would leave the book crossed,
because matching must happen first. The matching rules live in the engine.

    Book
     ├── bids: BookSide  (best = highest price)
     ├── asks: BookSide  (best = lowest price)
     └── index: order id → Order, for O(1) lookup and cancel

    BookSide: price → PriceLevel, plus a sorted list of prices
    PriceLevel: the orders at one price, oldest first
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass

from microstructure.models import Order, Side


class BookError(ValueError):
    """An operation would break the book's rules."""


class InvariantError(AssertionError):
    """The book's internal structure is inconsistent: a bug, not a user error."""


class PriceLevel:
    """All resting orders at one price on one side, oldest first.

    Stored in a dict, which keeps insertion order: appending, finding the oldest order,
    and removing any order by id are all O(1).
    """

    __slots__ = ("price", "_orders", "total")

    def __init__(self, price: int) -> None:
        self.price = price
        self._orders: dict[int, Order] = {}
        self.total = 0  # sum of remaining quantity, kept up to date for O(1) depth

    def append(self, order: Order) -> None:
        self._orders[order.order_id] = order
        self.total += order.remaining

    def first(self) -> Order:
        """The order with time priority at this price."""
        return next(iter(self._orders.values()))

    def remove(self, order: Order) -> None:
        del self._orders[order.order_id]
        self.total -= order.remaining

    def __iter__(self) -> Iterator[Order]:
        return iter(self._orders.values())

    def __len__(self) -> int:
        return len(self._orders)


class BookSide:
    """One side of the book: price levels, with the best price found in O(1)."""

    __slots__ = ("side", "_levels", "_prices")

    def __init__(self, side: Side) -> None:
        self.side = side
        self._levels: dict[int, PriceLevel] = {}
        self._prices: list[int] = []  # ascending; best bid is the last, best ask the first

    def best(self) -> int | None:
        if not self._prices:
            return None
        return self._prices[-1] if self.side is Side.BUY else self._prices[0]

    def level(self, price: int) -> PriceLevel | None:
        return self._levels.get(price)

    def levels(self) -> Iterator[PriceLevel]:
        """Price levels from best to worst."""
        prices = reversed(self._prices) if self.side is Side.BUY else iter(self._prices)
        return (self._levels[p] for p in prices)

    def add(self, order: Order) -> None:
        level = self._levels.get(order.price)
        if level is None:
            level = self._levels[order.price] = PriceLevel(order.price)
            bisect.insort(self._prices, order.price)  # O(levels); books have few levels
        level.append(order)

    def remove_level(self, price: int) -> None:
        """Drop an empty price level."""
        del self._levels[price]
        del self._prices[bisect.bisect_left(self._prices, price)]

    def __len__(self) -> int:
        """Number of price levels."""
        return len(self._prices)


@dataclass(frozen=True, slots=True)
class LevelView:
    """A read-only summary of one price level, for display."""

    price: int
    quantity: int
    orders: int


class Book:
    """Resting orders on both sides of one instrument."""

    def __init__(self) -> None:
        self.bids = BookSide(Side.BUY)
        self.asks = BookSide(Side.SELL)
        self._index: dict[int, Order] = {}
        self.last_seq = 0  # arrival number of the newest order inserted

    def side(self, side: Side) -> BookSide:
        return self.bids if side is Side.BUY else self.asks

    def best_bid(self) -> int | None:
        return self.bids.best()

    def best_ask(self) -> int | None:
        return self.asks.best()

    def spread(self) -> int | None:
        """Best ask minus best bid in ticks, or None if either side is empty."""
        bid, ask = self.best_bid(), self.best_ask()
        return None if bid is None or ask is None else ask - bid

    def crosses(self, side: Side, price: int) -> bool:
        """Would an order at this price trade against the other side?"""
        best = self.side(side.opposite).best()
        if best is None:
            return False
        return price >= best if side is Side.BUY else price <= best

    def insert(self, order: Order) -> None:
        """Rest an order in the book. The caller (the engine) must have matched it first."""
        if order.remaining < 1:
            raise BookError(f"order {order.order_id} has nothing left to rest")
        if order.order_id in self._index:
            raise BookError(f"order {order.order_id} is already in the book")
        if order.seq <= self.last_seq:
            # Time priority is arrival order, so arrivals must be numbered in increasing order.
            raise BookError(f"order {order.order_id} has arrival number {order.seq}, "
                            f"but {self.last_seq} was already used")
        if self.crosses(order.side, order.price):
            raise BookError(f"a {order.side.value} at {order.price} would cross the book "
                            f"(bid {self.best_bid()}, ask {self.best_ask()}); match it first")
        self.side(order.side).add(order)
        self._index[order.order_id] = order
        self.last_seq = order.seq

    def fill(self, order_id: int, quantity: int) -> Order:
        """Take `quantity` from a resting order; remove it once nothing remains.

        Returns the order, whose `remaining` shows what is left. A partly filled order keeps
        its place in the queue, because only its quantity changes.
        """
        order = self._index.get(order_id)
        if order is None:
            raise BookError(f"order {order_id} is not resting in the book")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= order.remaining:
            raise BookError(f"can fill 1 to {order.remaining} of order {order_id}, not {quantity!r}")
        level = self.side(order.side).level(order.price)
        order.remaining -= quantity
        level.total -= quantity
        if order.remaining == 0:
            self._take_out(order, level)
        return order

    def remove(self, order_id: int) -> Order:
        """Take a resting order out of the book (a cancel). Its `remaining` is what was removed."""
        order = self._index.get(order_id)
        if order is None:
            raise BookError(f"order {order_id} is not resting in the book")
        self._take_out(order, self.side(order.side).level(order.price))
        return order

    def _take_out(self, order: Order, level: PriceLevel) -> None:
        level.remove(order)
        del self._index[order.order_id]
        if len(level) == 0:
            self.side(order.side).remove_level(order.price)

    def get(self, order_id: int) -> Order | None:
        return self._index.get(order_id)

    def __contains__(self, order_id: object) -> bool:
        return order_id in self._index

    def __len__(self) -> int:
        """Number of resting orders."""
        return len(self._index)

    def orders_at(self, side: Side, price: int) -> list[Order]:
        """Orders resting at one price, in the order they will trade."""
        level = self.side(side).level(price)
        return list(level) if level else []

    def depth(self, side: Side, levels: int = 5) -> list[LevelView]:
        """The best `levels` price levels on one side, best first."""
        out = []
        for level in self.side(side).levels():
            if len(out) == levels:
                break
            out.append(LevelView(level.price, level.total, len(level)))
        return out


def find_problems(book: Book) -> list[str]:
    """Every way the book's structure is inconsistent. An empty list means it's valid."""
    problems: list[str] = []
    seen: dict[int, Order] = {}
    for book_side in (book.bids, book.asks):
        name = book_side.side.value
        if book_side._prices != sorted(set(book_side._prices)):
            problems.append(f"{name} prices are not sorted and unique: {book_side._prices}")
        if set(book_side._prices) != set(book_side._levels):
            problems.append(f"{name} price list {sorted(book_side._prices)} doesn't match "
                            f"its levels {sorted(book_side._levels)}")
        for price, level in book_side._levels.items():
            where = f"{name} level {price}"
            if level.price != price:
                problems.append(f"{where} thinks its price is {level.price}")
            if len(level) == 0:
                problems.append(f"{where} is empty but still in the book")
            total = sum(o.remaining for o in level)
            if level.total != total:
                problems.append(f"{where} total is {level.total} but its orders add up to {total}")
            previous_seq = 0
            for key, order in level._orders.items():
                if key != order.order_id:
                    problems.append(f"{where} stores order {order.order_id} under id {key}")
                if order.side is not book_side.side:
                    problems.append(f"{where} holds order {order.order_id}, a {order.side.value}")
                if order.price != price:
                    problems.append(f"{where} holds order {order.order_id} priced {order.price}")
                if order.remaining < 1:
                    problems.append(f"{where} holds order {order.order_id} with nothing remaining")
                if order.seq <= previous_seq:
                    problems.append(f"{where} has order {order.order_id} out of arrival order")
                if order.seq > book.last_seq:
                    problems.append(f"order {order.order_id} has arrival number {order.seq}, "
                                    f"newer than the newest recorded ({book.last_seq})")
                previous_seq = order.seq
                if order.order_id in seen:
                    problems.append(f"order {order.order_id} appears more than once")
                seen[order.order_id] = order
    if seen.keys() != book._index.keys():
        problems.append(f"id index {sorted(book._index)} doesn't match resting orders {sorted(seen)}")
    else:
        for order_id, order in seen.items():
            if book._index[order_id] is not order:
                problems.append(f"id index points order {order_id} at a different object")
    bid, ask = book.best_bid(), book.best_ask()
    if bid is not None and ask is not None and bid >= ask:
        problems.append(f"book is crossed: best bid {bid} >= best ask {ask}")
    return problems


def check_invariants(book: Book) -> None:
    """Raise InvariantError listing every problem, if there are any."""
    problems = find_problems(book)
    if problems:
        raise InvariantError("order book is inconsistent:\n- " + "\n- ".join(problems))
