import pytest

from microstructure import BookError, LevelView, MatchingEngine, Order, OrderError, Side, Status, check_invariants
from microstructure.book import Book

BUY, SELL = Side.BUY, Side.SELL


@pytest.fixture
def engine():
    return MatchingEngine()


def test_first_order_rests(engine):
    result = engine.submit(BUY, 100, 5)
    assert (result.order_id, result.status, result.trades, result.filled, result.resting) == \
        (1, Status.RESTING, (), 0, 5)
    assert result.average_price is None
    assert engine.book.best_bid() == 100


def test_order_below_the_ask_rests_and_at_the_ask_trades(engine):
    engine.submit(SELL, 101, 5)
    assert engine.submit(BUY, 100, 5).status is Status.RESTING
    assert engine.submit(BUY, 101, 5).status is Status.FILLED


def test_exact_fill_removes_both_orders_and_the_level(engine):
    engine.submit(SELL, 101, 5)
    result = engine.submit(BUY, 101, 5)
    assert result.status is Status.FILLED
    assert len(engine.book) == 0 and engine.book.best_ask() is None and len(engine.book.asks) == 0
    check_invariants(engine.book)


def test_partly_filled_resting_order_keeps_its_place(engine):
    engine.submit(SELL, 101, 5)  # 1
    engine.submit(SELL, 101, 5)  # 2, behind 1
    engine.submit(BUY, 101, 2)   # takes 2 from order 1
    assert [(o.order_id, o.remaining) for o in engine.book.orders_at(SELL, 101)] == [(1, 3), (2, 5)]
    result = engine.submit(BUY, 101, 4)  # order 1 still goes first
    assert [(t.sell_order_id, t.quantity) for t in result.trades] == [(1, 3), (2, 1)]


def test_buyer_gets_the_resting_price_not_its_limit(engine):
    engine.submit(SELL, 101, 5)
    result = engine.submit(BUY, 105, 5)
    assert [t.price for t in result.trades] == [101]


def test_sweep_stops_at_the_limit_and_rests_the_rest(engine):
    for price in (101, 102, 103):
        engine.submit(SELL, price, 2)
    result = engine.submit(BUY, 102, 10)
    assert [(t.price, t.quantity) for t in result.trades] == [(101, 2), (102, 2)]
    assert (result.status, result.filled, result.resting) == (Status.PARTIALLY_FILLED, 4, 6)
    assert engine.book.depth(BUY) == [LevelView(102, 6, 1)]
    assert engine.book.depth(SELL) == [LevelView(103, 2, 1)]
    check_invariants(engine.book)


def test_ids_and_trades_are_numbered_in_order(engine):
    engine.submit(SELL, 101, 1)
    engine.submit(SELL, 101, 1)
    result = engine.submit(BUY, 101, 2)
    assert result.order_id == 3
    assert [t.trade_id for t in engine.trades] == [1, 2]
    assert engine.submit(BUY, 90, 1).order_id == 4


@pytest.mark.parametrize("args", [
    ("buy", 100, 5),
    (BUY, 0, 5),
    (BUY, 100.0, 5),
    (BUY, 100, 0),
    (BUY, 100, True),
    (BUY, 100, 5, "x" * 51),
    (BUY, 100, 5, None),
])
def test_invalid_orders_are_refused_without_using_an_id(engine, args):
    with pytest.raises(OrderError):
        engine.submit(*args)
    assert engine.submit(BUY, 100, 1).order_id == 1
    assert len(engine.book) == 1


def test_fill_rejects_bad_requests():
    book = Book()
    book.insert(Order(1, SELL, 101, 5, 5, 1))
    for order_id, quantity in [(2, 1), (1, 0), (1, 6), (1, True), (1, 1.0)]:
        with pytest.raises(BookError):
            book.fill(order_id, quantity)
    assert book.get(1).remaining == 5
    check_invariants(book)
