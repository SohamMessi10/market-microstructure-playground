# Walkthrough: matching by hand

This works through one sequence of orders by hand, step by step, using the rules in
[`design.md`](design.md). `tests/test_walkthrough.py` replays exactly these orders through the
engine and checks every number below, so this page can't drift from what the code does.

Prices are in ticks. Order ids are given in arrival order, so a smaller id arrived earlier.

## 1. Build a book

| # | Order | Result |
|---|---|---|
| 1 | sell 5 @ 101 | the book is empty, so nothing to trade against: rests |
| 2 | sell 3 @ 101 | rests **behind** order 1 at the same price (time priority) |
| 3 | sell 4 @ 102 | rests one tick higher |
| 4 | buy 6 @ 100 | 100 is below the best ask of 101, so it doesn't cross: rests |

```
        SELL (asks)                 BUY (bids)
  102 │ #3 ×4                 
  101 │ #1 ×5, #2 ×3            ← best ask 101
──────┼──────────────────── spread: 101 − 100 = 1 tick
  100 │                         #4 ×6   ← best bid 100
```

## 2. A buy that sweeps two price levels

**Order 5: buy 10 @ 102.** It is willing to pay up to 102, and the best ask is 101, so it
crosses. It trades against the best price first, and at each price against the oldest order:

| Step | Against | Why this one | Quantity | Price | Left to fill |
|---|---|---|---|---|---|
| 1 | #1 | best price (101), oldest there | min(10, 5) = **5** | 101 | 5 |
| 2 | #2 | still 101, next oldest | min(5, 3) = **3** | 101 | 2 |
| 3 | #3 | 101 is empty; next best is 102 | min(2, 4) = **2** | 102 | 0 |

- Order 5 is **filled**: 5 + 3 + 2 = 10.
- It paid the *resting* prices, 101, 101 and 102, never more than its 102 limit. Its average
  price is (5×101 + 3×101 + 2×102) / 10 = **101.2** ticks.
- Order 3 was **partially filled**: 2 of its 4 traded, and its remaining 2 keep their place.

```
  102 │ #3 ×2                   ← best ask 102
──────┼──────────────────── spread: 102 − 100 = 2 ticks
  100 │                         #4 ×6   ← best bid 100
```

## 3. A sell that gets a better price than it asked for, then rests

**Order 6: sell 8 @ 99.** It will take as little as 99, and the best bid is 100, so it crosses.

| Step | Against | Quantity | Price | Left |
|---|---|---|---|---|
| 1 | #4 | min(8, 6) = **6** | **100** | 2 |

- It trades at 100, the resting buyer's price: one tick **better** than its own limit.
- The bid side is now empty, so the remaining 2 can't trade. They **rest** at the order's own
  limit, 99, and become the new best ask. Order 6 is **partially filled**.

```
  102 │ #3 ×2
   99 │ #6 ×2                   ← best ask 99
──────┼──────────────────── no bids: no best bid, no spread
```

## 4. Check the quantities add up

| Order | Size | Traded | Resting | |
|---|---|---|---|---|
| #1 sell | 5 | 5 | 0 | filled |
| #2 sell | 3 | 3 | 0 | filled |
| #3 sell | 4 | 2 | 2 | partially filled |
| #4 buy | 6 | 6 | 0 | filled |
| #5 buy | 10 | 10 | 0 | filled |
| #6 sell | 8 | 6 | 2 | partially filled |

Bought in trades: 10 (order 5) + 6 (order 4) = 16. Sold in trades: 5 + 3 + 2 + 6 = 16. Every
trade has one buyer and one seller, so the two always match. Four trades in total:
5 @ 101, 3 @ 101, 2 @ 102, 6 @ 100.
