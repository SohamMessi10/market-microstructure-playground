# Progress

## Status

Milestone 2 of 6 complete: matching and partial fills. Cancellation comes next.
The exchange rules and full plan are in [`docs/design.md`](docs/design.md).

## Milestones

### Milestone 1: models, book, and invariants
- `models.py`: `Side`, `Order` (with `remaining` and an arrival number `seq`), `Trade`, and
  strict price and quantity checks (whole ticks and units; `True` and `1.0` are refused).
- `book.py`: `PriceLevel` (orders at one price in arrival order, stored in an insertion-ordered
  dict so append, oldest-first, and remove-by-id are O(1)), `BookSide` (levels plus a sorted
  price list for the best price in O(1)), and `Book` (both sides, an id index, best bid/ask,
  spread, depth, orders at a price).
- `Book.insert` refuses an order that would cross, a duplicate id, an arrival number that isn't
  newer than the last, and an order with nothing remaining. Matching is the engine's job.
- `find_problems` / `check_invariants` check the book's whole structure: non-empty levels,
  correct level totals, side and price of each order, arrival order, the price list, the id
  index, and that the book isn't crossed.
- Tests: hand-built books; 16 deliberate corruptions, each of which the checker must catch;
  a Hypothesis test that inserts random orders and compares best prices, depth, FIFO order, and
  crossing refusals with a brute-force model.
- Mutation-checked by hand: swapped best bid/ask, an order at the best price not counted as
  crossing (both sides), level totals not updated, unsorted prices, stale arrival numbers
  accepted, depth ignoring its limit, and the checker missing an equal-price crossed book each
  fail a test. Two mutants first survived (the checker allowing two orders with the same arrival
  number, and not detecting an order stored twice); a corruption test was added for each.
- The random test was measured to exercise real cases: over 300 runs, 558 refused crossing
  orders, books up to 13 price levels, and up to 4 orders queued at one price.

### Milestone 2: matching and partial fills
- `engine.py`: `MatchingEngine.submit(side, price, quantity)` trades an incoming order against
  the best resting orders, oldest first at each price, at the resting price, until it is filled
  or no longer crosses; any remainder rests at its limit. Returns a `SubmitResult` (trades,
  status, filled, resting, average price). One counter supplies both order ids and arrival
  numbers, so they can't disagree; an invalid order is refused before it uses an id.
- `Book.fill` takes quantity from a resting order without moving it in its queue, and removes
  the order, and its price level if empty, once nothing remains.
- `docs/walkthrough.md` works through six orders by hand (a two-level sweep, price improvement,
  a partial fill that rests). `tests/test_walkthrough.py` replays it and checks every number.
- `tests/reference.py`: a deliberately simple engine (one flat list, full search per fill) that
  shares no code with the real one. Hypothesis compares trades and both sides of the book after
  every order, on three kinds of random sequences: a narrow price band, a wide one, and deep
  sweeps (10–60 small orders, then 1–5 large ones).
- Property tests check, after every order: invariants (including not crossed), quantity
  conservation for the order and both sides of the book, trade price = resting price and never
  worse than the limit, best prices first, consecutive trade ids, and determinism.
- Mutation-checked: 13 deliberate bugs (trade at the incoming price, newest first, under-filling,
  no remainder resting, stale level totals, empty levels kept, one trade per order, wrong seller
  id, wrong status, repeated trade ids, lost trades, unweighted average price, removing the wrong
  price level) each fail a test. The reference comparison alone catches the four central ones.
- Coverage was measured, not assumed. The first random generators never had one order trade more
  than 3–4 times, so deep sweeps were barely tested. Adding the deep-sweep generator raised that
  to 12 trades across 11 price levels from a single order.

## Commands verified

| Where | Python | Command | Result |
|---|---|---|---|
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 61 passed (milestone 1) |
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 82 passed (milestone 2) |

## Next

Milestone 3: cancellation. Cancelling removes only the remaining quantity; cancelling an
unknown or finished order is refused with a reason. Each order's history is tracked so that
original = filled + resting + cancelled can be checked, with a stateful Hypothesis test mixing
submits and cancels.

## Concepts to review
- What an order book is: bids, asks, best bid and ask, spread, depth.
- Price-time priority, and why time is an arrival number rather than a clock.
- Why prices are integer ticks.
- Why the book (data) is separate from the engine (rules).
- Choosing data structures by operation cost: dict for FIFO with O(1) removal, sorted list
  with bisect for the best price.
- Testing the tester: why the invariant checker needs its own corruption tests.
- Price improvement: why the incoming order trades at the resting price.
- Differential testing against a simple reference implementation.
- Measuring what random tests generate, instead of assuming they cover the hard cases.
