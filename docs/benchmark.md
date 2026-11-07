# Benchmark

Run it yourself with `python benchmarks/bench.py` (add `--profile` for a profile). Results depend
on the machine, so the script starts every report with the Python version and the CPU.

## Setup

- **Machine:** Claude's Linux workspace, Intel Xeon @ 2.30 GHz, 2 logical CPUs.
- **Python:** CPython 3.13.16, one thread.
- **What is timed:** `engine.submit` and `engine.cancel` for every event, starting from an empty
  engine. Generating the workload, parsing, and output are not timed.
- **Repeats:** 5 timed runs per workload, and the whole script was run 3 times. The tables give
  the range of the three medians, because the same run varies by up to about 20% on this machine.

## Workloads

Both are generated from a fixed seed, so every run replays exactly the same events.

| Workload | Events | What it contains | Result |
|---|---|---|---|
| typical | 200,000 | 70% passive orders 1–20 ticks from a drifting mid, 10% aggressive orders up to 5 ticks through it, 20% cancels of one of the last 1,000 orders | 159,773 orders, 86,650 trades, 26,460 cancelled; 46,237 resting in 108 price levels at the end |
| deep book | 200,000 | 80% passive orders spread over 20,000 ticks, 20% cancels; nothing crosses | 127,931 resting in 19,967 price levels at the end |

## Results

| Workload | Events per second (median, 3 runs) | Time per event |
|---|---:|---:|
| typical | 188,000 – 209,000 | 4.8 – 5.3 µs |
| deep book | 227,000 – 236,000 | 4.2 – 4.4 µs |

### Against the simple reference engine

`tests/reference.py` is the deliberately simple engine the tests compare against: one flat
list, searched in full for every fill. Same typical workload, median of 3:

| Events | Resting at the end | This engine | Reference | Ratio |
|---:|---:|---:|---:|---:|
| 2,000 | 891 | 6.5 ms | 38.6 ms | 6× |
| 5,000 | 2,088 | 18.1 ms | 260.9 ms | 14× |
| 20,000 | 8,187 | 67.4 ms | 4,305 ms | 64× |

This engine's time grows in proportion to the number of events (3.2–3.6 µs each here). The
reference engine searches every resting order on each fill, so its cost per event grows with
the book, and the gap widens as the book grows. That is the point of the price levels and the
id index.

## What the measurements answered

**Is the sorted price list a bottleneck?** The design chose a sorted Python list with `bisect`
for each side's prices, which costs time proportional to the number of levels to add or remove
a level, and noted that this should be measured rather than assumed. With almost 20,000 levels,
the deep-book workload is no slower than the typical one with about 100. Inserting into a list of
20,000 integers moves at most 160 KB of contiguous memory, which is small next to the Python
work done per order. A balanced tree or heap would only matter far beyond this size.

**Does removing duplicate validation help?** A profile of the typical workload showed every
order's price and quantity being checked twice (once in `submit`, again when the `Order` is
built). The duplicated checks took about a tenth of the profiled time (0.33 of 3.04 s). Removing the first
check and measuring it properly, with 12 alternating runs of each version, changed throughput
by −1.0% (typical) and −3.7% (deep book): no real difference. `cProfile` adds overhead to every
function call, so it exaggerates the cost of small functions that are called often. The change
was reverted, because the original, which validates everything before touching any state, is
easier to read.

## Where the time goes

From `python benchmarks/bench.py --profile` on the typical workload (time spent in each
function itself, with the profiler's own overhead included):

| Function | Calls | Share of time |
|---|---:|---|
| `MatchingEngine.submit` (the matching loop itself) | 159,773 | largest |
| `Order.__post_init__` (field validation) | 159,773 | second |
| `isinstance` (validation checks) | about 3 million | third |
| `Book.crosses` | 343,158 | |
| `Book.fill` | 86,650 | |

Most of the time is ordinary Python function-call and attribute overhead spread across small
steps, not one slow operation. Going substantially faster would mean a different
implementation language for the matching core (the brief's suggested C++ port), not a better
algorithm.

## Caveats

- One machine, one Python version. A laptop will give different numbers; run the script.
- A synthetic workload, not real market data. Real order flow has bursts, many more cancels,
  and very uneven activity across price levels.
- Throughput of the engine alone. A real exchange's latency is dominated by networking,
  persistence, and risk checks, none of which exist here.
