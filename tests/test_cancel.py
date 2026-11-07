import pytest

from microstructure import InvariantError, LevelView, MatchingEngine, OrderError, OrderState, Side

BUY, SELL = Side.BUY, Side.SELL


@pytest.fixture
def engine():
    return MatchingEngine()


def test_cancel_a_resting_order(engine):
    engine.submit(BUY, 99, 5)
    engine.submit(BUY, 100, 5)
    result = engine.cancel(2)
    assert (result.ok, result.order_id, result.cancelled, result.reason) == (True, 2, 5, "")
    assert engine.book.best_bid() == 99 and 2 not in engine.book
    assert engine.book.bids.level(100) is None  # its now-empty level is gone
    record = engine.order(2)
    assert (record.state, record.filled, record.cancelled, record.resting) == (OrderState.CANCELLED, 0, 5, 0)
    engine.check()


def test_cancel_removes_only_what_has_not_traded(engine):
    engine.submit(SELL, 101, 10)
    engine.submit(BUY, 101, 4)   # fills 4 of order 1
    result = engine.cancel(1)
    assert result.cancelled == 6
    record = engine.order(1)
    assert (record.quantity, record.filled, record.cancelled, record.resting) == (10, 4, 6, 0)
    assert [t.quantity for t in engine.trades] == [4]  # the trade still stands
    engine.check()


def test_cancel_the_rested_part_of_an_incoming_order(engine):
    engine.submit(SELL, 101, 3)
    engine.submit(BUY, 102, 10)  # trades 3, rests 7
    assert engine.cancel(2).cancelled == 7
    assert engine.order(2).filled == 3
    assert len(engine.book) == 0
    engine.check()


def test_cancel_in_the_middle_of_a_queue_keeps_the_others_in_order(engine):
    for _ in range(3):
        engine.submit(SELL, 101, 2)
    engine.cancel(2)
    assert [o.order_id for o in engine.book.orders_at(SELL, 101)] == [1, 3]
    assert engine.book.depth(SELL) == [LevelView(101, 4, 2)]
    result = engine.submit(BUY, 101, 3)
    assert [(t.sell_order_id, t.quantity) for t in result.trades] == [(1, 2), (3, 1)]
    engine.check()


def test_a_cancelled_order_never_trades(engine):
    engine.submit(SELL, 101, 5)
    engine.cancel(1)
    result = engine.submit(BUY, 105, 5)
    assert result.trades == () and engine.book.best_bid() == 105


@pytest.mark.parametrize("setup,order_id,reason", [
    (lambda e: None, 7, "there is no order 7"),
    (lambda e: (e.submit(SELL, 101, 5), e.submit(BUY, 101, 5)), 1, "order 1 already traded in full"),
    (lambda e: (e.submit(SELL, 101, 5), e.submit(BUY, 101, 5)), 2, "order 2 already traded in full"),
    (lambda e: (e.submit(SELL, 101, 5), e.cancel(1)), 1, "order 1 was already cancelled"),
    (lambda e: (e.submit(SELL, 101, 5), e.submit(BUY, 101, 2), e.cancel(1)), 1, "order 1 was already cancelled"),
])
def test_refused_cancels_give_a_reason_and_change_nothing(engine, setup, order_id, reason):
    setup(engine)
    before = (engine.orders(), list(engine.trades), len(engine.book))
    result = engine.cancel(order_id)
    assert (result.ok, result.cancelled, result.reason) == (False, 0, reason)
    assert (engine.orders(), list(engine.trades), len(engine.book)) == before
    engine.check()


@pytest.mark.parametrize("order_id", ["1", 1.0, None, True])
def test_cancel_needs_a_whole_number_id(engine, order_id):
    engine.submit(BUY, 100, 5)
    with pytest.raises(OrderError):
        engine.cancel(order_id)
    assert 1 in engine.book


def test_cancels_do_not_use_up_order_ids(engine):
    engine.submit(BUY, 100, 5)
    engine.cancel(1)
    engine.cancel(99)
    assert engine.submit(BUY, 100, 5).order_id == 2


def test_records_are_copies(engine):
    engine.submit(BUY, 100, 5)
    engine.order(1).filled = 5
    engine.orders()[0].cancelled = 5
    assert (engine.order(1).filled, engine.order(1).cancelled) == (0, 0)
    assert engine.order(2) is None


def test_record_states(engine):
    engine.submit(SELL, 101, 5)
    assert engine.order(1).state is OrderState.OPEN
    engine.submit(BUY, 101, 2)
    assert engine.order(1).state is OrderState.OPEN      # partly filled, still resting
    assert engine.order(2).state is OrderState.FILLED
    engine.submit(BUY, 101, 3)
    assert engine.order(1).state is OrderState.FILLED


# --- the engine-wide check must catch accounting errors -------------------------------

def busy_engine():
    engine = MatchingEngine()
    engine.submit(SELL, 101, 5)   # 1
    engine.submit(SELL, 102, 5)   # 2
    engine.submit(BUY, 101, 3)    # 3: trades 3 with order 1
    engine.submit(BUY, 99, 4)     # 4: rests
    engine.cancel(2)
    engine.check()
    return engine


def corrupt_filled(engine):
    engine._orders[1].filled += 1


def corrupt_cancelled(engine):
    engine._orders[4].cancelled = 1


def corrupt_book_quantity(engine):
    order = engine.book.get(4)
    order.remaining -= 1
    engine.book.bids.level(99).total -= 1


def corrupt_trade_side(engine):
    trade = engine.trades[0]
    engine.trades[0] = type(trade)(trade.trade_id, trade.price, trade.quantity, trade.sell_order_id,
                                   trade.buy_order_id, trade.aggressor)


def corrupt_trade_unknown_order(engine):
    trade = engine.trades[0]
    engine.trades[0] = type(trade)(trade.trade_id, trade.price, trade.quantity, 99,
                                   trade.sell_order_id, trade.aggressor)


def corrupt_over_cancelled(engine):
    engine._orders[2].cancelled = 9


def corrupt_orphan_book_order(engine):
    del engine._orders[4]


@pytest.mark.parametrize("corrupt,message", [
    (corrupt_filled, "records 4 filled"),
    (corrupt_cancelled, "should have 3 resting"),
    (corrupt_book_quantity, "but the book has 3"),
    (corrupt_trade_side, "as a buyer"),
    (corrupt_trade_unknown_order, "order 99"),
    (corrupt_over_cancelled, "doesn't add up"),
    (corrupt_orphan_book_order, "no open record"),
])
def test_engine_check_catches_accounting_errors(corrupt, message):
    engine = busy_engine()
    corrupt(engine)
    with pytest.raises(InvariantError, match=message):
        engine.check()
