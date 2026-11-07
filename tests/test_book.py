import pytest
from hypothesis import given
from hypothesis import strategies as st

from microstructure import Book, BookError, InvariantError, LevelView, Order, Side, check_invariants, find_problems


class Orders:
    """Makes orders with increasing ids and arrival numbers, as the engine will."""

    def __init__(self):
        self.n = 0

    def __call__(self, side, price, quantity=10, remaining=None):
        self.n += 1
        return Order(self.n, side, price, quantity, quantity if remaining is None else remaining, self.n)


@pytest.fixture
def new():
    return Orders()


def sample_book(new):
    """bids 99 (two orders), 98; asks 101, 102 (two orders)."""
    book = Book()
    for order in [new(Side.BUY, 99, 10), new(Side.SELL, 101, 5), new(Side.BUY, 98, 7),
                  new(Side.BUY, 99, 3), new(Side.SELL, 102, 4), new(Side.SELL, 102, 6)]:
        book.insert(order)
    check_invariants(book)
    return book


def test_empty_book():
    book = Book()
    assert (book.best_bid(), book.best_ask(), book.spread(), len(book)) == (None, None, None, 0)
    assert book.depth(Side.BUY) == [] and book.depth(Side.SELL) == []
    check_invariants(book)


def test_best_prices_and_spread(new):
    book = sample_book(new)
    assert (book.best_bid(), book.best_ask(), book.spread()) == (99, 101, 2)


def test_depth_aggregates_each_level_best_first(new):
    book = sample_book(new)
    assert book.depth(Side.BUY) == [LevelView(99, 13, 2), LevelView(98, 7, 1)]
    assert book.depth(Side.SELL) == [LevelView(101, 5, 1), LevelView(102, 10, 2)]
    assert book.depth(Side.SELL, levels=1) == [LevelView(101, 5, 1)]


def test_orders_at_one_price_keep_arrival_order(new):
    book = sample_book(new)
    assert [o.order_id for o in book.orders_at(Side.BUY, 99)] == [1, 4]
    assert [o.order_id for o in book.orders_at(Side.SELL, 102)] == [5, 6]
    assert book.orders_at(Side.BUY, 50) == []


def test_lookup_by_id(new):
    book = sample_book(new)
    assert book.get(3).price == 98 and 3 in book
    assert book.get(99) is None and 99 not in book
    assert len(book) == 6


@pytest.mark.parametrize("side,price", [
    (Side.BUY, 101),   # at the best ask: would trade
    (Side.BUY, 150),
    (Side.SELL, 99),   # at the best bid: would trade
    (Side.SELL, 1),
])
def test_insert_refuses_an_order_that_would_cross(new, side, price):
    book = sample_book(new)
    with pytest.raises(BookError, match="would cross"):
        book.insert(new(side, price))
    assert len(book) == 6
    check_invariants(book)


@pytest.mark.parametrize("side,price", [(Side.BUY, 100), (Side.SELL, 100)])
def test_an_order_inside_the_spread_rests(new, side, price):
    book = sample_book(new)
    book.insert(new(side, price))
    check_invariants(book)
    assert book.spread() == 1


def test_insert_refuses_duplicates_stale_arrivals_and_empty_orders(new):
    book = sample_book(new)
    with pytest.raises(BookError, match="already in the book"):
        book.insert(Order(1, Side.BUY, 90, 5, 5, 100))
    with pytest.raises(BookError, match="arrival number"):
        book.insert(Order(50, Side.BUY, 90, 5, 5, 3))
    with pytest.raises(BookError, match="nothing left"):
        book.insert(Order(51, Side.BUY, 90, 5, 0, 101))
    check_invariants(book)


# --- the invariant checker must catch each kind of corruption ------------------------
# If it couldn't, every later test that relies on it would pass for the wrong reason.

def corrupt_level_total(book):
    book.bids.level(99).total += 1


def corrupt_empty_level(book):
    level = book.asks.level(101)
    del level._orders[2]
    level.total = 0
    del book._index[2]


def corrupt_unsorted_prices(book):
    book.asks._prices.reverse()


def corrupt_price_list(book):
    book.bids._prices.append(97)


def corrupt_wrong_side(book):
    book.bids.level(98).first().side = Side.SELL


def corrupt_wrong_price(book):
    book.bids.level(98).first().price = 97


def corrupt_arrival_order(book):
    level = book.bids.level(99)
    first, second = list(level._orders)
    level._orders = {second: level._orders[second], first: level._orders[first]}


def corrupt_index_missing(book):
    del book._index[3]


def corrupt_index_object(book):
    original = book._index[3]
    book._index[3] = Order(3, original.side, original.price, original.quantity, original.remaining, original.seq)


def corrupt_crossed(book):
    order = Order(7, Side.BUY, 101, 1, 1, 7)
    book.bids.add(order)
    book._index[7] = order
    book.last_seq = 7


def corrupt_zero_remaining(book):
    order = book.asks.level(101).first()
    order.remaining = 0
    book.asks.level(101).total = 0


def corrupt_stored_under_wrong_id(book):
    level = book.bids.level(98)
    level._orders = {33: level.first()}


def corrupt_future_arrival(book):
    book.last_seq = 2


def corrupt_level_price(book):
    book.asks.level(102).price = 103


def corrupt_same_arrival_number(book):
    first, second = book.bids.level(99)
    second.seq = first.seq


def corrupt_order_in_two_levels(book):
    order = book.asks.level(101).first()
    book.asks.level(102)._orders[order.order_id] = order
    book.asks.level(102).total += order.remaining


@pytest.mark.parametrize("corrupt,message", [
    (corrupt_level_total, "total is"),
    (corrupt_empty_level, "is empty"),
    (corrupt_unsorted_prices, "not sorted"),
    (corrupt_price_list, "doesn't match its levels"),
    (corrupt_wrong_side, "a sell"),
    (corrupt_wrong_price, "priced 97"),
    (corrupt_arrival_order, "out of arrival order"),
    (corrupt_index_missing, "id index"),
    (corrupt_index_object, "different object"),
    (corrupt_crossed, "crossed"),
    (corrupt_zero_remaining, "nothing remaining"),
    (corrupt_stored_under_wrong_id, "under id 33"),
    (corrupt_future_arrival, "newer than the newest"),
    (corrupt_level_price, "thinks its price"),
    (corrupt_same_arrival_number, "out of arrival order"),
    (corrupt_order_in_two_levels, "more than once"),
])
def test_checker_catches_corruption(new, corrupt, message):
    book = sample_book(new)
    corrupt(book)
    assert any(message in p for p in find_problems(book)), find_problems(book)
    with pytest.raises(InvariantError, match=message):
        check_invariants(book)


# --- random inserts, compared with a brute-force model --------------------------------

order_requests = st.lists(
    st.tuples(st.sampled_from(Side), st.integers(1, 30), st.integers(1, 50)),
    max_size=60,
)


@given(order_requests)
def test_random_inserts_match_a_brute_force_model(requests):
    book, resting = Book(), []
    for n, (side, price, quantity) in enumerate(requests, start=1):
        bids = [o.price for o in resting if o.side is Side.BUY]
        asks = [o.price for o in resting if o.side is Side.SELL]
        would_cross = (asks and price >= min(asks)) if side is Side.BUY else (bids and price <= max(bids))
        order = Order(n, side, price, quantity, quantity, n)
        if would_cross:
            with pytest.raises(BookError):
                book.insert(order)
        else:
            book.insert(order)
            resting.append(order)
        check_invariants(book)

    bids = [o for o in resting if o.side is Side.BUY]
    asks = [o for o in resting if o.side is Side.SELL]
    assert book.best_bid() == max((o.price for o in bids), default=None)
    assert book.best_ask() == min((o.price for o in asks), default=None)
    assert len(book) == len(resting)
    for side, orders, best_first in ((Side.BUY, bids, True), (Side.SELL, asks, False)):
        prices = sorted({o.price for o in orders}, reverse=best_first)
        expected = [LevelView(p, sum(o.remaining for o in orders if o.price == p),
                              sum(1 for o in orders if o.price == p)) for p in prices]
        assert book.depth(side, levels=len(prices) + 1) == expected
        for p in prices:  # FIFO: same price, arrival order
            assert book.orders_at(side, p) == [o for o in orders if o.price == p]
