"""Random order sequences: the engine must agree with the reference engine and keep every rule."""

from hypothesis import given, settings
from hypothesis import strategies as st

from microstructure import MatchingEngine, Side, Status, check_invariants
from tests.reference import ReferenceEngine

# Mostly small orders that build up the book, plus some large ones that sweep through it.
quantities = st.integers(1, 20) | st.integers(50, 300)
# A narrow price band, so most orders cross and many trade against several resting orders.
orders = st.lists(st.tuples(st.sampled_from(Side), st.integers(95, 105), quantities), max_size=80)
# A wide band, where most orders rest and the book grows many levels.
wide_orders = st.lists(st.tuples(st.sampled_from(Side), st.integers(1, 1000), quantities), max_size=80)
# Build a deep book of small orders first, then send large orders through it, so single
# orders trade against many resting orders across many price levels.
sweeps = st.builds(
    lambda small, large: small + large,
    st.lists(st.tuples(st.sampled_from(Side), st.integers(90, 110), st.integers(1, 10)), min_size=10, max_size=60),
    st.lists(st.tuples(st.sampled_from(Side), st.integers(85, 115), st.integers(50, 400)), min_size=1, max_size=5),
)


def book_of(engine, side):
    return [(o.order_id, o.price, o.remaining) for level in engine.book.side(side).levels() for o in level]


def check_against_reference(requests):
    engine, reference = MatchingEngine(), ReferenceEngine()
    for side, price, quantity in requests:
        result = engine.submit(side, price, quantity)
        expected_trades, expected_resting = reference.submit(side, price, quantity)
        assert [(t.price, t.quantity, t.buy_order_id, t.sell_order_id) for t in result.trades] == expected_trades
        assert result.resting == expected_resting
        assert book_of(engine, Side.BUY) == reference.book(Side.BUY)
        assert book_of(engine, Side.SELL) == reference.book(Side.SELL)
        check_invariants(engine.book)


@given(orders)
def test_matches_the_reference_engine(requests):
    check_against_reference(requests)


@given(wide_orders)
def test_matches_the_reference_engine_with_a_deep_book(requests):
    check_against_reference(requests)


@given(sweeps)
def test_matches_the_reference_engine_through_deep_sweeps(requests):
    check_against_reference(requests)


@given(orders | sweeps)
def test_every_submit_follows_the_rules(requests):
    engine = MatchingEngine()
    for side, price, quantity in requests:
        resting_before = {o.order_id: (o.price, o.remaining)
                          for level in engine.book.side(side.opposite).levels() for o in level}
        opposite_total = sum(r for _, r in resting_before.values())
        same_total = sum(lvl.total for lvl in engine.book.side(side).levels())
        trade_id_before = len(engine.trades)

        result = engine.submit(side, price, quantity)
        check_invariants(engine.book)  # includes: the book is not crossed

        # Quantity: what traded plus what rests is the order's size, and trades add up.
        assert result.filled + result.resting == quantity
        assert sum(t.quantity for t in result.trades) == result.filled
        assert result.status is (Status.FILLED if result.resting == 0
                                 else Status.PARTIALLY_FILLED if result.filled else Status.RESTING)
        # The other side lost exactly what traded; this side gained exactly what rested.
        assert sum(lvl.total for lvl in engine.book.side(side.opposite).levels()) == opposite_total - result.filled
        assert sum(lvl.total for lvl in engine.book.side(side).levels()) == same_total + result.resting
        if result.resting:
            assert engine.book.get(result.order_id).price == price

        prices = [t.price for t in result.trades]
        for trade in result.trades:
            assert trade.aggressor is side and trade.incoming_order_id == result.order_id
            # Each trade is at the resting order's price, never worse than the incoming limit.
            assert trade.price == resting_before[trade.resting_order_id][0]
            assert trade.price <= price if side is Side.BUY else trade.price >= price
            # A resting order can't trade more than it had.
            assert trade.quantity <= resting_before[trade.resting_order_id][1]
        # Best price first: a buy pays rising prices, a sell receives falling ones.
        assert prices == sorted(prices, reverse=side is Side.SELL)
        # Trade ids are consecutive across the whole run.
        assert [t.trade_id for t in result.trades] == list(range(trade_id_before + 1,
                                                                 trade_id_before + 1 + len(result.trades)))
        assert engine.trades[trade_id_before:] == list(result.trades)


@settings(max_examples=50)
@given(orders)
def test_same_orders_same_trades(requests):
    def run():
        engine = MatchingEngine()
        for request in requests:
            engine.submit(*request)
        return engine.trades, book_of(engine, Side.BUY), book_of(engine, Side.SELL)

    assert run() == run()
