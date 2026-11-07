"""Command line: `mmp replay script.jsonl`.

Exit codes:
    0  replayed successfully
    1  the script can't be replayed (missing file, bad line); nothing was run
    2  the command itself was wrong (unknown option, missing argument)
    3  the engine failed its own consistency check after the replay: a bug, please report it
"""

from __future__ import annotations

import argparse
import sys

from microstructure import __version__
from microstructure.book import InvariantError
from microstructure.replay import ScriptError, format_json, format_text, read_script, replay

EXIT_OK, EXIT_SCRIPT, EXIT_USAGE, EXIT_BUG = 0, 1, 2, 3


def depth_arg(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {text!r}") from None
    if not 1 <= value <= 50:
        raise argparse.ArgumentTypeError(f"must be between 1 and 50, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mmp", description="Market Microstructure Playground: replay orders through a limit order book.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("replay", help="replay a script of orders and cancels",
                              description="Replay a JSON Lines script of orders and cancels and show what happened.")
    run.add_argument("script", help="a .jsonl file, one order or cancel per line")
    run.add_argument("--format", choices=["text", "json"], default="text",
                     help="text (default) for people, json for programs: one object per event")
    run.add_argument("--depth", type=depth_arg, default=5,
                     help="price levels per side in the final book (text format; default 5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        events = read_script(args.script)
    except ScriptError as exc:
        print(f"mmp: {args.script} can't be replayed:\n{exc}", file=sys.stderr)
        return EXIT_SCRIPT

    engine, steps = replay(events)
    try:
        engine.check()
    except InvariantError as exc:
        print(f"mmp: internal error, the engine is inconsistent after the replay:\n{exc}", file=sys.stderr)
        return EXIT_BUG

    sys.stdout.write(format_json(steps) if args.format == "json" else format_text(engine, steps, args.depth))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
