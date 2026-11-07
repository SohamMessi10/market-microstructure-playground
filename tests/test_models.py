import pytest

from microstructure import Order, OrderError, Side, Trade
from microstructure.models import MAX_PRICE, MAX_QUANTITY, check_price, check_quantity


def test_opposite_side():
    assert Side.BUY.opposite is Side.SELL
    assert Side.SELL.opposite is Side.BUY


@pytest.mark.parametrize("value", [1, 100, MAX_PRICE])
def test_valid_prices(value):
    assert check_price(value) == value


@pytest.mark.parametrize("value", [0, -1, MAX_PRICE + 1, 1.0, 1.5, "10", None, True, False])
def test_invalid_prices(value):
    with pytest.raises(OrderError):
        check_price(value)


@pytest.mark.parametrize("value", [0, -5, MAX_QUANTITY + 1, 2.0, "3", None, True])
def test_invalid_quantities(value):
    with pytest.raises(OrderError):
        check_quantity(value)


def make(**changes):
    fields = dict(order_id=1, side=Side.BUY, price=100, quantity=10, remaining=10, seq=1)
    fields.update(changes)
    return Order(**fields)


def test_order_tracks_filled_quantity():
    order = make(remaining=4)
    assert order.filled == 6


@pytest.mark.parametrize("changes", [
    {"side": "buy"},
    {"price": 0},
    {"quantity": 0},
    {"remaining": 11},
    {"remaining": -1},
    {"remaining": True},
    {"order_id": 0},
    {"seq": 0},
    {"seq": True},
    {"order_id": "1"},
])
def test_order_rejects_invalid_fields(changes):
    with pytest.raises(OrderError):
        make(**changes)


def test_trade_knows_which_order_was_resting():
    buy_took = Trade(1, price=100, quantity=5, buy_order_id=7, sell_order_id=3, aggressor=Side.BUY)
    assert (buy_took.resting_order_id, buy_took.incoming_order_id) == (3, 7)
    sell_took = Trade(2, price=100, quantity=5, buy_order_id=7, sell_order_id=3, aggressor=Side.SELL)
    assert (sell_took.resting_order_id, sell_took.incoming_order_id) == (7, 3)
