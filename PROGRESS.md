# Progress

## Status

Milestone 1 of 6 complete: models, book data structures, and invariants. Matching comes next.
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

## Commands verified

| Where | Python | Command | Result |
|---|---|---|---|
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 61 passed (milestone 1) |

## Next

Milestone 2: the matching engine. Incoming orders trade against the best resting orders at the
resting price, in price-time order, with partial fills resting the remainder. It will be
checked against a deliberately simple reference engine on random order sequences.

## Concepts to review
- What an order book is: bids, asks, best bid and ask, spread, depth.
- Price-time priority, and why time is an arrival number rather than a clock.
- Why prices are integer ticks.
- Why the book (data) is separate from the engine (rules).
- Choosing data structures by operation cost: dict for FIFO with O(1) removal, sorted list
  with bisect for the best price.
- Testing the tester: why the invariant checker needs its own corruption tests.
