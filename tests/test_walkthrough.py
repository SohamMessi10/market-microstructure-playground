"""Replays docs/walkthrough.md through the engine and checks every number in it."""

from collections import Counter

from microstructure import LevelView, MatchingEngine, Side, Status, Trade, check_invariants

BUY, SELL = Side.BUY, Side.SELL


def test_walkthrough():
    engine = MatchingEngine()
    book = engine.book

    # 1. Build a book.
    for side, price, quantity in [(SELL, 101, 5), (SELL, 101, 3), (SELL, 102, 4), (BUY, 100, 6)]:
        assert engine.submit(side, price, quantity).status is Status.RESTING
        check_invariants(book)
    assert [o.order_id for o in book.orders_at(SELL, 101)] == [1, 2]  # #2 behind #1
    assert (book.best_bid(), book.best_ask(), book.spread()) == (100, 101, 1)

    # 2. Order 5: buy 10 @ 102 sweeps two levels.
    result = engine.submit(BUY, 102, 10)
    check_invariants(book)
    assert result.status is Status.FILLED and (result.filled, result.resting) == (10, 0)
    assert result.trades == (
        Trade(1, price=101, quantity=5, buy_order_id=5, sell_order_id=1, aggressor=BUY),
        Trade(2, price=101, quantity=3, buy_order_id=5, sell_order_id=2, aggressor=BUY),
        Trade(3, price=102, quantity=2, buy_order_id=5, sell_order_id=3, aggressor=BUY),
    )
    assert result.average_price == 101.2
    assert book.get(3).remaining == 2 and 1 not in book and 2 not in book
    assert book.depth(SELL) == [LevelView(102, 2, 1)]
    assert (book.best_bid(), book.best_ask(), book.spread()) == (100, 102, 2)

    # 3. Order 6: sell 8 @ 99 trades at 100 (better than its limit), then rests 2 @ 99.
    result = engine.submit(SELL, 99, 8)
    check_invariants(book)
    assert result.status is Status.PARTIALLY_FILLED and (result.filled, result.resting) == (6, 2)
    assert result.trades == (Trade(4, price=100, quantity=6, buy_order_id=4, sell_order_id=6, aggressor=SELL),)
    assert book.depth(BUY) == []
    assert book.depth(SELL) == [LevelView(99, 2, 1), LevelView(102, 2, 1)]
    assert (book.best_bid(), book.best_ask(), book.spread()) == (None, 99, None)

    # 4. The quantities add up.
    assert [(t.quantity, t.price) for t in engine.trades] == [(5, 101), (3, 101), (2, 102), (6, 100)]
    traded = Counter()
    for t in engine.trades:
        traded[t.buy_order_id] += t.quantity
        traded[t.sell_order_id] += t.quantity
    assert traded == {1: 5, 2: 3, 3: 2, 4: 6, 5: 10, 6: 6}  # the table's "Traded" column
    resting = {order_id: book.get(order_id).remaining for order_id in (3, 6)}
    assert resting == {3: 2, 6: 2} and len(book) == 2      # its "Resting" column
    sizes = {1: 5, 2: 3, 3: 4, 4: 6, 5: 10, 6: 8}
    assert all(traded[i] + resting.get(i, 0) == sizes[i] for i in sizes)
    bought, sold = traded[4] + traded[5], traded[1] + traded[2] + traded[3] + traded[6]
    assert bought == sold == 16

    # 5. Cancel what's left of order 3: only its 2 resting units go.
    result = engine.cancel(3)
    assert (result.ok, result.cancelled) == (True, 2)
    record = engine.order(3)
    assert (record.quantity, record.filled, record.resting, record.cancelled) == (4, 2, 0, 2)
    assert book.depth(SELL) == [LevelView(99, 2, 1)] and book.best_ask() == 99
    assert len(engine.trades) == 4  # the earlier trade with order 5 stands
    assert engine.cancel(3).reason == "order 3 was already cancelled"
    assert engine.cancel(1).reason == "order 1 already traded in full"
    engine.check()
