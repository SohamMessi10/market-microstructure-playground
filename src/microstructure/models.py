"""Orders, trades, and the checks every price and quantity must pass.

Prices are whole numbers of ticks and quantities are whole numbers of units, so the
engine never rounds. Converting ticks to a display price (say 1 tick = $0.01) happens
only at the edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_PRICE = 1_000_000_000  # ticks; a sanity limit, not an exchange rule
MAX_QUANTITY = 1_000_000_000


class Side(Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderError(ValueError):
    """An order's fields are invalid."""


def check_price(price: object) -> int:
    # bool is a subclass of int, so True would otherwise be accepted as a price of 1.
    if isinstance(price, bool) or not isinstance(price, int):
        raise OrderError(f"price must be a whole number of ticks, got {price!r}")
    if not 1 <= price <= MAX_PRICE:
        raise OrderError(f"price must be between 1 and {MAX_PRICE} ticks, got {price}")
    return price


def check_quantity(quantity: object) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise OrderError(f"quantity must be a whole number, got {quantity!r}")
    if not 1 <= quantity <= MAX_QUANTITY:
        raise OrderError(f"quantity must be between 1 and {MAX_QUANTITY}, got {quantity}")
    return quantity


@dataclass(slots=True)
class Order:
    """A limit order, as it rests in the book.

    `remaining` shrinks as the order is filled; the other fields never change.
    `seq` is the engine's arrival number: lower means it arrived earlier, which decides
    priority between orders at the same price.
    """

    order_id: int
    side: Side
    price: int
    quantity: int  # original size
    remaining: int
    seq: int
    trader: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.side, Side):
            raise OrderError(f"side must be Side.BUY or Side.SELL, got {self.side!r}")
        check_price(self.price)
        check_quantity(self.quantity)
        if isinstance(self.remaining, bool) or not isinstance(self.remaining, int) \
                or not 0 <= self.remaining <= self.quantity:
            raise OrderError(f"remaining must be between 0 and the quantity {self.quantity}, "
                             f"got {self.remaining!r}")
        for name in ("order_id", "seq"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise OrderError(f"{name} must be a whole number of at least 1, got {value!r}")

    @property
    def filled(self) -> int:
        return self.quantity - self.remaining


@dataclass(frozen=True, slots=True)
class Trade:
    """One execution between a resting order and an incoming one, at the resting price."""

    trade_id: int
    price: int
    quantity: int
    buy_order_id: int
    sell_order_id: int
    aggressor: Side  # the side of the incoming order, which took liquidity

    @property
    def resting_order_id(self) -> int:
        return self.sell_order_id if self.aggressor is Side.BUY else self.buy_order_id

    @property
    def incoming_order_id(self) -> int:
        return self.buy_order_id if self.aggressor is Side.BUY else self.sell_order_id
