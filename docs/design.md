# Market Microstructure Playground: design

## Problem

Most people who trade, or study finance, never see the mechanism that turns orders into trades.
A stock's "price" is really two prices, the best bid and the best ask, and every trade is the
result of an exact, mechanical rule: **price-time priority**. This project builds that mechanism
from scratch, small enough to step through by hand, with tests that prove it follows the rules.

**User:** finance learners, and engineers preparing for trading-systems interviews.
**Not:** a trading tool. One made-up instrument, no real orders, no brokerage connection.
It is also separate from a backtester: it models how one book matches orders, not strategies
over historical prices.

## Simplified exchange rules

These are the rules the engine implements and the tests check. Real exchanges have many more.

1. **One instrument.** Prices are whole numbers of **ticks** (the smallest price step) of at
   least 1. Quantities are whole numbers of at least 1. No fractional prices, so no rounding.
2. **Limit orders only** (for the MVP): buy at most, or sell at least, a given price. Orders stay
   until filled or cancelled (good till cancelled).
3. **Price-time priority.** A better price goes first: higher for buys, lower for sells. At the
   same price, the order that arrived first goes first (FIFO). "Arrival" is the engine's own
   sequence number, never a wall clock, so a replay always produces identical results.
4. **Matching.** An incoming order that crosses the book (a buy at or above the best ask, or a
   sell at or below the best bid) trades against the best resting orders, one at a time, until it
   is filled or no longer crosses.
5. **Trade price is the resting order's price.** The order that was waiting set the price; the
   incoming order may get a better price than its limit, never a worse one.
6. **Partial fills.** If the incoming order isn't fully filled, the rest of it joins the book at
   its limit price. A resting order that is partly filled keeps its place in the queue.
7. **After matching, the book is never crossed:** best bid < best ask whenever both exist.
8. **Cancellation removes only the remaining quantity.** What already traded stays traded.
   Cancelling an unknown or already finished order is refused with a reason, and a replay
   continues.
9. **Not modelled:** market orders (a possible extension, which needs an explicit rule for an
   empty book), modifying orders (cancel and resubmit, which loses queue position, as on real
   exchanges), self-trade prevention, fees, lot sizes, auctions, hidden or iceberg orders, and
   more than one instrument.

## Invariants (checked after every event in tests)

- **Book structure:** every price level holds at least one order; a level's total equals the sum
  of its orders' remaining quantities; every order sits on its own side at its own price; within
  a level orders are in arrival order; the sorted price list matches the levels; the id index
  holds exactly the resting orders.
- **Not crossed:** best bid < best ask.
- **Quantity conservation:** for every order, original quantity = filled + resting + cancelled;
  its recorded fills equal the sum of its trades; its resting quantity equals what the book
  holds for it. Every trade names a real buy order and a real sell order, so total bought
  always equals total sold. `MatchingEngine.check()` verifies all of this.
- **Determinism:** the same events always produce the same trades and book.

## Architecture

```
 scripted events (JSONL) ──► replay ──► MatchingEngine ──► trades + event results
                                           │ owns ids, sequence numbers, the rules
                                           ▼
                                         Book: bids and asks, price levels, id index
                                           │  pure data structure; refuses inserts that cross
                                           ▼
                              display: best bid/ask, depth, trade log
```

- **`models.py`:** `Side`, `Order` (resting state), `Trade`; validation of prices and quantities.
- **`book.py`:** `PriceLevel` (orders at one price, FIFO), `BookSide` (levels sorted by price),
  `Book` (both sides plus an id index), and `check_invariants`.
- **`engine.py`:** `MatchingEngine.submit` applies rules 3–7 and returns the trades, the
  status (filled, partially filled, resting) and the quantity left resting. `cancel` applies
  rule 8: it removes the resting quantity, or refuses with a reason (no such order, already
  traded in full, already cancelled). The engine keeps an `OrderRecord` for every order it
  accepted (filled, cancelled, resting, state), which is what makes conservation checkable.
  Records are never discarded, so memory grows with the number of orders; that is fine for
  a simulator that replays scripted sessions, and a real engine would archive finished ones.
- **`replay.py`** (milestone 4): reads a scripted event file and replays it deterministically.

### Data structures

| Need | Structure | Cost |
|---|---|---|
| Orders at one price, FIFO, cancel any | `dict` (insertion-ordered) of id → order | O(1) append, peek, remove |
| Best price on a side | sorted list of prices (`bisect`) | O(1) best; O(levels) to add or drop a level |
| Find an order to cancel | `dict` of id → order | O(1) |

A sorted list costs O(levels) to add a new price, but books have few active price levels and
the list is contiguous memory, so it is simpler and usually faster than a tree in Python. The
benchmark milestone measures this rather than assuming it.

## Testing strategy

- Hand-worked examples, written out step by step, then reproduced by the engine
  ([`walkthrough.md`](walkthrough.md) and `tests/test_walkthrough.py`).
- Hypothesis property tests: random event sequences, with every invariant checked after every
  event, and results compared against a deliberately simple reference engine.
- Mutation testing by hand: break a rule on purpose, confirm a test fails.
- Tests for the invariant checker itself: corrupt a book in each way and confirm it's caught.

## Milestones

1. Models, book data structures, and invariants. *(complete)*
2. Matching and partial fills, with a reference engine for differential tests. *(complete)*
3. Cancellation and quantity conservation, with stateful property tests. *(complete)*
4. Scripted replay and a command-line tool.
5. Visualization: step through a replay and see the book and trades.
6. Benchmark (with workload and machine details) and README.
