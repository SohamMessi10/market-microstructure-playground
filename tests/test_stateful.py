"""Random interleavings of orders and cancels, checked against the reference engine at every step."""

from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from microstructure import MatchingEngine, OrderState, Side
from tests.reference import ReferenceEngine

REASONS = {"there is no order": "unknown", "already traded in full": "filled", "was already cancelled": "cancelled"}


def reason_kind(reason):
    return next(kind for text, kind in REASONS.items() if text in reason)


def book_of(engine, side):
    return [(o.order_id, o.price, o.remaining) for level in engine.book.side(side).levels() for o in level]


class Exchange(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.engine = MatchingEngine()
        self.reference = ReferenceEngine()
        self.submitted = 0

    @rule(side=st.sampled_from(Side), price=st.integers(95, 105),
          quantity=st.integers(1, 20) | st.integers(50, 200))
    def submit(self, side, price, quantity):
        result = self.engine.submit(side, price, quantity)
        expected_trades, expected_resting = self.reference.submit(side, price, quantity)
        self.submitted += 1
        assert [(t.price, t.quantity, t.buy_order_id, t.sell_order_id) for t in result.trades] == expected_trades
        assert result.resting == expected_resting

    @precondition(lambda self: self.submitted)
    @rule(data=st.data())
    def cancel_an_order(self, data):
        # Any order so far: resting, partly filled, filled, or already cancelled.
        order_id = data.draw(st.integers(1, self.submitted), label="order_id")
        before = self.engine.order(order_id)
        result = self.engine.cancel(order_id)
        expected = self.reference.cancel(order_id)
        if isinstance(expected, int):
            assert result.ok and result.cancelled == expected == before.resting
            after = self.engine.order(order_id)
            assert after.filled == before.filled  # what traded stays traded
            assert after.state is OrderState.CANCELLED
        else:
            assert not result.ok and result.cancelled == 0 and reason_kind(result.reason) == expected

    @rule(order_id=st.integers(-5, 0) | st.integers(10_000, 10_010))
    def cancel_an_order_that_never_existed(self, order_id):
        result = self.engine.cancel(order_id)
        assert not result.ok and reason_kind(result.reason) == "unknown" == self.reference.cancel(order_id)

    @invariant()
    def books_match_the_reference(self):
        assert book_of(self.engine, Side.BUY) == self.reference.book(Side.BUY)
        assert book_of(self.engine, Side.SELL) == self.reference.book(Side.SELL)

    @invariant()
    def every_order_is_accounted_for(self):
        self.engine.check()  # book structure, not crossed, and quantity = filled + resting + cancelled
        for record in self.engine.orders():
            expected = self.reference.history[record.order_id]
            assert (record.quantity, record.filled, record.cancelled) == \
                   (expected["quantity"], expected["filled"], expected["cancelled"])
        bought = sum(r.filled for r in self.engine.orders() if r.side is Side.BUY)
        sold = sum(r.filled for r in self.engine.orders() if r.side is Side.SELL)
        assert bought == sold == sum(t.quantity for t in self.engine.trades)


TestExchange = Exchange.TestCase
