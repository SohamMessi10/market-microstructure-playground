"""Measure how fast the matching engine processes orders and cancels.

    python benchmarks/bench.py                 # the default workloads, 5 runs each
    python benchmarks/bench.py --events 20000  # quicker
    python benchmarks/bench.py --profile       # where the time goes, for the "typical" workload

Every number printed comes from this machine and this run; the report starts with the Python
version and CPU so results from different machines aren't compared by accident. Workloads are
generated from a fixed seed, so the same command always replays the same orders.

What is timed: `engine.submit` and `engine.cancel` for every event, in a fresh engine. Not
timed: generating the workload, parsing scripts, or output.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import platform
import pstats
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

from microstructure import MatchingEngine, Side

# ("order", side, price, quantity) or ("cancel", order_id)
Event = tuple


def typical_workload(n: int, seed: int = 1) -> list[Event]:
    """Order flow around a drifting mid price.

    70% passive limit orders 1-20 ticks from the mid on their own side, 10% aggressive orders
    priced up to 5 ticks through the mid (they trade, often against several resting orders),
    20% cancels of one of the last 1,000 orders (some already traded, so those are refused).
    The mid takes a one-tick random step every 50 events or so.
    """
    rng = random.Random(seed)
    mid, events, submitted = 10_000, [], 0
    for _ in range(n):
        if rng.random() < 0.02:
            mid += rng.choice((-1, 1))
        roll = rng.random()
        if roll < 0.20 and submitted:
            events.append(("cancel", rng.randint(max(1, submitted - 999), submitted)))
            continue
        side = rng.choice((Side.BUY, Side.SELL))
        sign = -1 if side is Side.BUY else 1  # passive buys below the mid, sells above
        if roll < 0.90:
            price = mid + sign * rng.randint(1, 20)
            quantity = rng.randint(1, 100)
        else:
            price = mid - sign * rng.randint(0, 5)
            quantity = rng.randint(50, 500)
        events.append(("order", side, price, quantity))
        submitted += 1
    return events


def deep_workload(n: int, seed: int = 2) -> list[Event]:
    """A book with thousands of price levels: passive orders spread over 20,000 ticks.

    This is the worst case for the sorted price list, where adding or removing a level costs
    time proportional to the number of levels. 80% orders, 20% cancels; nothing crosses.
    """
    rng = random.Random(seed)
    events, submitted = [], 0
    for _ in range(n):
        if rng.random() < 0.20 and submitted:
            events.append(("cancel", rng.randint(1, submitted)))
            continue
        side = rng.choice((Side.BUY, Side.SELL))
        price = rng.randint(1, 10_000) if side is Side.BUY else rng.randint(10_001, 20_000)
        events.append(("order", side, price, rng.randint(1, 100)))
        submitted += 1
    return events


def run(events: list[Event], engine=None):
    engine = engine or MatchingEngine()
    submit, cancel = engine.submit, engine.cancel
    for event in events:
        if event[0] == "order":
            submit(event[1], event[2], event[3])
        else:
            cancel(event[1])
    return engine


def time_runs(events: list[Event], repeat: int, make_engine=MatchingEngine) -> list[float]:
    seconds = []
    for _ in range(repeat):
        engine = make_engine()
        start = time.perf_counter()
        run(events, engine)
        seconds.append(time.perf_counter() - start)
    return seconds


def cpu_name() -> str:
    try:
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                  text=True, timeout=5).stdout.strip() or platform.machine()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine()


def describe(engine: MatchingEngine) -> str:
    records = engine.orders()
    cancels = sum(1 for r in records if r.cancelled)
    return (f"{len(records):,} orders, {len(engine.trades):,} trades, {cancels:,} cancelled, "
            f"{len(engine.book):,} resting at the end in {len(engine.book.bids) + len(engine.book.asks):,} price levels")


def report(name: str, events: list[Event], repeat: int) -> None:
    engine = run(events)
    engine.check()  # the workload is valid and the engine stayed consistent
    seconds = time_runs(events, repeat)
    rates = sorted(len(events) / s for s in seconds)
    print(f"\n{name}: {len(events):,} events -> {describe(engine)}")
    print(f"  events per second over {repeat} runs: median {statistics.median(rates):,.0f}, "
          f"range {rates[0]:,.0f} to {rates[-1]:,.0f}")
    print(f"  median time per event: {statistics.median(seconds) / len(events) * 1e6:.2f} µs")


def compare_with_reference(max_events: int, repeat: int) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tests.reference import ReferenceEngine  # the deliberately simple engine the tests use

    repeat = min(repeat, 3)  # the reference engine is slow
    print(f"\nthe engine vs the simple reference engine (one flat list, full search per fill), "
          f"typical workload, median of {repeat}:")
    for n in (2_000, 5_000, 20_000):
        if n > max_events:
            break
        events = typical_workload(n)
        resting = len(run(events).book)
        fast = statistics.median(time_runs(events, repeat))
        slow = statistics.median(time_runs(events, repeat, make_engine=ReferenceEngine))
        print(f"  {n:>6,} events ({resting:,} resting at the end): engine {fast * 1000:,.1f} ms, "
              f"reference {slow * 1000:,.1f} ms, {slow / fast:,.0f}x faster")


def profile(events: list[Event]) -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    run(events)
    profiler.disable()
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats("tottime").print_stats(12)
    print("\nprofile of the typical workload, by time spent in each function itself:")
    print("\n".join(line for line in out.getvalue().splitlines()
                    if line.strip() and not line.startswith(("   Ordered by", "         "))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=int, default=200_000, help="events per workload (default 200,000)")
    parser.add_argument("--repeat", type=int, default=5, help="timed runs per workload (default 5)")
    parser.add_argument("--profile", action="store_true", help="also profile the typical workload")
    args = parser.parse_args(argv)
    if args.events < 1 or args.repeat < 1:
        parser.error("--events and --repeat must be at least 1")

    print(f"Python {platform.python_version()} ({platform.python_implementation()}) on "
          f"{platform.system()} {platform.machine()}, {cpu_name()}, {os.cpu_count()} logical CPUs")
    print("single thread; timing covers engine.submit and engine.cancel only")
    report("typical", typical_workload(args.events), args.repeat)
    report("deep book", deep_workload(args.events), args.repeat)
    compare_with_reference(args.events, args.repeat)
    if args.profile:
        profile(typical_workload(args.events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
