"""The command line, including golden files: saved output that the replay must reproduce exactly.

If a change to the engine alters any trade, price, or message, these tests fail. When the
change is intended, regenerate the files and review the difference before committing:

    mmp replay examples/walkthrough.jsonl > tests/golden/walkthrough.txt
    mmp replay examples/walkthrough.jsonl --format json > tests/golden/walkthrough.jsonl
    (and the same for queue_priority)
"""

import subprocess
import sys
from pathlib import Path

import pytest

from microstructure import InvariantError, MatchingEngine, __version__
from microstructure.cli import EXIT_BUG, EXIT_OK, EXIT_SCRIPT, EXIT_USAGE, main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ["walkthrough", "queue_priority"]


@pytest.mark.parametrize("name", EXAMPLES)
@pytest.mark.parametrize("fmt,suffix", [("text", "txt"), ("json", "jsonl")])
def test_examples_match_their_golden_files(capsys, name, fmt, suffix):
    assert main(["replay", str(ROOT / "examples" / f"{name}.jsonl"), "--format", fmt]) == EXIT_OK
    out, err = capsys.readouterr()
    assert err == ""
    assert out == (ROOT / "tests" / "golden" / f"{name}.{suffix}").read_text(encoding="utf-8")


def test_bad_script_exits_1_and_explains_on_stderr(capsys, tmp_path):
    script = tmp_path / "bad.jsonl"
    script.write_text('{"type": "order", "side": "buy", "price": 100, "quantity": 5}\n{"type": "cancel"}\n')
    assert main(["replay", str(script)]) == EXIT_SCRIPT
    out, err = capsys.readouterr()
    assert out == ""  # nothing ran, so nothing is printed as if it had
    assert "line 2: cancel is missing order_id" in err


def test_missing_file_exits_1(capsys, tmp_path):
    assert main(["replay", str(tmp_path / "nope.jsonl")]) == EXIT_SCRIPT
    assert "no such file" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["replay"], ["replay", "x.jsonl", "--format", "xml"],
                                  ["replay", "x.jsonl", "--depth", "0"], ["replay", "x.jsonl", "--depth", "two"],
                                  ["frobnicate"]])
def test_usage_errors_exit_2(capsys, argv):
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == EXIT_USAGE
    assert capsys.readouterr().err


def test_depth_limits_the_final_book(capsys, tmp_path):
    script = tmp_path / "deep.jsonl"
    script.write_text("".join(f'{{"type": "order", "side": "buy", "price": {p}, "quantity": 1}}\n'
                              for p in range(90, 100)))
    assert main(["replay", str(script), "--depth", "2"]) == EXIT_OK
    bids = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  bid")]
    assert [b.split()[1] for b in bids] == ["99", "98"]


def test_an_inconsistent_engine_exits_3(capsys, monkeypatch, tmp_path):
    def broken_check(self):
        raise InvariantError("simulated bug")

    monkeypatch.setattr(MatchingEngine, "check", broken_check)
    script = tmp_path / "s.jsonl"
    script.write_text('{"type": "order", "side": "buy", "price": 100, "quantity": 5}\n')
    assert main(["replay", str(script)]) == EXIT_BUG
    out, err = capsys.readouterr()
    assert out == "" and "simulated bug" in err


def test_readme_example_output_is_real():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = readme.split("This is the real output of `mmp replay examples/queue_priority.jsonl`:", 1)[1]
    shown = block.split("```", 2)[1].removeprefix("\n")
    assert shown == (ROOT / "tests" / "golden" / "queue_priority.txt").read_text(encoding="utf-8")


def test_installed_command_and_module_both_run():
    version = subprocess.run([sys.executable, "-m", "microstructure.cli", "--version"],
                             capture_output=True, text=True, check=True)
    assert version.stdout.strip() == f"mmp {__version__}"
    run = subprocess.run([sys.executable, "-m", "microstructure.cli", "replay",
                          str(ROOT / "examples" / "walkthrough.jsonl")], capture_output=True, text=True)
    assert run.returncode == EXIT_OK
    assert run.stdout == (ROOT / "tests" / "golden" / "walkthrough.txt").read_text(encoding="utf-8")
