"""Keeps the benchmark script working: its workloads are valid and deterministic, and it runs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))

import bench  # noqa: E402


def test_workloads_are_deterministic():
    assert bench.typical_workload(2_000) == bench.typical_workload(2_000)
    assert bench.deep_workload(2_000) == bench.deep_workload(2_000)
    assert bench.typical_workload(2_000, seed=1) != bench.typical_workload(2_000, seed=9)


def test_typical_workload_has_the_described_mix():
    events = bench.typical_workload(20_000)
    cancels = sum(e[0] == "cancel" for e in events) / len(events)
    assert 0.18 < cancels < 0.22
    engine = bench.run(events)
    engine.check()
    assert len(engine.trades) > 1_000                     # aggressive orders really trade
    assert any(r.cancelled for r in engine.orders())      # cancels really cancel


def test_deep_workload_builds_many_levels_and_never_trades():
    engine = bench.run(bench.deep_workload(20_000))
    engine.check()
    assert engine.trades == []
    assert len(engine.book.bids) + len(engine.book.asks) > 5_000


def test_the_script_runs_and_states_the_machine(capsys):
    assert bench.main(["--events", "300", "--repeat", "1", "--profile"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Python ") and "logical CPUs" in out
    assert "typical: 300 events" in out and "deep book: 300 events" in out
    assert "profile of the typical workload" in out
