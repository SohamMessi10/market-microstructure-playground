# Progress

## Status

Milestone 5 of 6 complete: the step-through replay page. The benchmark and README come next.
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

### Milestone 3: cancellation and quantity conservation
- `MatchingEngine.cancel(order_id)` removes only the resting quantity and returns a
  `CancelResult`. Cancelling an unknown order, one that already traded in full, or one already
  cancelled is refused with a reason and changes nothing; it is a result rather than an
  exception, because late cancels are normal and a replay should carry on.
- The engine keeps an `OrderRecord` per order (quantity, filled, cancelled, resting, state:
  open, filled, cancelled). `order()` and `orders()` return copies.
- `MatchingEngine.check()` adds accounting to the book's checks: quantity = filled + resting +
  cancelled for every order, recorded fills equal that order's trades, resting quantity equals
  what the book holds, every trade names a real buyer and seller, and the book holds no order
  without an open record. 7 deliberate corruptions, each of which it must catch.
- `Book.remove` takes an order out (a cancel), dropping its price level if it empties.
- The walkthrough gains a step 5: cancelling a partly filled order, then two refused cancels.
- The reference engine gains its own cancel and order history. A Hypothesis state machine
  interleaves orders, cancels of any earlier order, and cancels of ids that never existed, and
  after every step compares trades, both sides of the book, and every order's history with the
  reference, and checks total bought = total sold. Measured over 100 runs: 281 successful
  cancels (70 after a partial fill), 333 refused as filled, 208 as already cancelled.
- Mutation-checked: 12 deliberate bugs (cancel not recorded, cancel counted as the whole order,
  level total or id index not updated, no "already filled" check, resting or incoming fills not
  recorded, a partly filled cancelled order not marked cancelled, the check ignoring fills,
  book quantities or trade sides, an unknown cancel reported as success) each fail a test. The
  state machine alone catches the four central ones.

### Milestone 4: scripted replay and the `mmp` command
- `replay.py`: a JSON Lines script format (orders and cancels; `#` comments and blank lines
  skipped; optional trader and note). Parsing is strict and finishes before anything runs:
  every bad line is listed with its line number (up to 20 shown), and a script with any error
  doesn't run. File problems (missing, a folder, not UTF-8) are reported the same way; a UTF-8
  byte order mark and Windows line endings are accepted.
- `replay()` runs the events through a new engine and records each result with the best bid
  and ask just afterwards. Output as a readable log (one line per event, notes, a summary, and
  the final book as a ladder with the spread in the middle) or as JSON Lines.
- `mmp replay SCRIPT [--format text|json] [--depth N]`, with exit codes 0 (replayed), 1 (script
  can't be replayed; nothing printed to stdout), 2 (usage), 3 (the engine failed its own check
  after the replay).
- Examples: `examples/walkthrough.jsonl` (the hand-worked walkthrough, including its cancels)
  and `examples/queue_priority.jsonl` (a later, higher bid goes first; equal bids queue).
  Their output was checked by hand, then saved in `tests/golden/`; tests require the replay to
  reproduce it exactly, in both formats, through `main()` and through a real subprocess.
- Property tests: replaying a random script equals calling the engine directly, step by step;
  replaying twice gives identical output; JSON output has one valid object per event.
- Mutation-checked: 12 deliberate bugs (unknown fields allowed, 100.0 accepted, cancels skipped,
  line numbers off by one, good lines run despite bad ones, changed wording, best prices taken
  before the event, the consistency check skipped, a byte order mark breaking parsing, comment
  lines becoming events, asks printed lowest first, cancel id 0 accepted). One survived at first
  (asks printed in the wrong order: every test book had a single ask level); the ladder test now
  uses two levels per side.

### Milestone 5: the step-through replay page
- `mmp view SCRIPT [-o PAGE.html] [--depth N] [--title T]` writes one self-contained HTML page
  (no server, no outside requests). `view.py` replays the script, capturing each event's book
  before and after; `templates/viewer.html` draws it.
- The page: a price ladder (highest price at the top, best ask and bid meeting at the spread);
  each row's bar is that price's queue, one segment per order, oldest on the left; quantity that
  traded or was cancelled in the step stays as a dashed segment in its exact place, and the new
  order is outlined. An event panel (what happened, the note, this step's trades), a trade log,
  buttons, a slider, ← → Home End, links to a step (`#step=5`), light and dark themes.
- `docs/demo/` holds the pages for both examples; a test keeps them in sync with the code.
  `docs/screenshots/` has four screenshots (desktop, queue, phone, dark).
- Security: script text is escaped inside the embedded JSON and inserted only as text; a
  Content-Security-Policy blocks all outside requests. Tested in Chromium with a note containing
  `</script><script>alert(1)</script>` and an `<img onerror>`: shown as plain text, no dialog,
  no injected element; and an image from another site is blocked by the policy.
- Browser tests (Playwright, optional `.[browser]` extra; they skip without it): stepping,
  keyboard, slider, deep links, the ladder's segments and labels, the trade log, refused
  cancels, the empty script, and every step of both examples at 390, 768 and 1280 px in light
  and dark mode with no sideways scrolling and no script errors. A new CI job installs Chromium
  and runs them with `REQUIRE_BROWSER=1`, so a missing browser fails instead of skipping.
- Bugs caught: (1) in review, a price level pushed out of view by a better price would have
  been drawn as if its orders had left; fixed by asking the book, with a regression test.
  (2) In screenshots, an average of 100.625 was displayed as 100.62; now up to 4 decimals.
  (3) A wrong expected value in a new test (my miscount of the sequence), corrected by hand.
- Mutation-checked: 13 deliberate bugs in the Python, JavaScript and CSS. Four survived at
  first: two were equivalent (one showed the slider guard was redundant; it was removed), and
  two were real gaps (a trade log one step ahead, and removing the Content-Security-Policy),
  now caught by a mid-replay log check and a real blocked-request test.

## Commands verified

| Where | Python | Command | Result |
|---|---|---|---|
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 61 passed (milestone 1) |
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 82 passed (milestone 2) |
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 107 passed (milestone 3) |
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 160 passed (milestone 4) |
| Claude's Linux workspace | 3.13 | `mmp replay` on both examples, both formats | matches tests/golden |
| Claude's Linux workspace | 3.11, 3.13, 3.14 | `python -m pytest`, dev and ci profiles | 190 passed with Playwright (3.13); browser tests skipped without it (milestone 5) |
| Claude's Linux workspace | 3.13, Chromium 141 | `REQUIRE_BROWSER=1 pytest tests/test_viewer_browser.py` | 14 passed |

## Next

Milestone 6: a measured benchmark (stating the workload, Python version and machine), a profile
of where the time goes, and the full README with resume and interview material.

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
- Stateful property testing: random sequences of operations with invariants after every step.
- Why a refused cancel is a result, not an exception.
- Golden-file tests: what they catch, and why their contents must be reviewed by hand.
- Validating input completely before acting on any of it.
- Why embedding data in HTML needs escaping (`</script>`), and what a Content-Security-Policy does.
- Equivalent mutants: when a surviving mutant means redundant code, not a missing test.
