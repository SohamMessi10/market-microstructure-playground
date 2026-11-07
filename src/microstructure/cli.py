"""Command line: `mmp replay script.jsonl` and `mmp view script.jsonl`.

Exit codes:
    0  replayed successfully
    1  the script can't be replayed (missing file, bad line) or the page can't be written;
       nothing was run or written
    2  the command itself was wrong (unknown option, missing argument)
    3  the engine failed its own consistency check after the replay: a bug, please report it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from microstructure import __version__
from microstructure.book import InvariantError
from microstructure.replay import ScriptError, format_json, format_text, read_script, replay
from microstructure.view import DEFAULT_DEPTH, ViewError, build_view, render_html

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

    view = commands.add_parser("view", help="make a web page that steps through a script",
                               description="Write a self-contained HTML page that steps through a script "
                                           "one event at a time. Open it in any browser; it needs no server.")
    view.add_argument("script", help="a .jsonl file, one order or cancel per line")
    view.add_argument("-o", "--output", help="where to write the page (default: the script's name with .html, "
                                             "in the current folder)")
    view.add_argument("--depth", type=depth_arg, default=DEFAULT_DEPTH,
                      help=f"price levels per side to draw (1 to 20; default {DEFAULT_DEPTH})")
    view.add_argument("--title", default="", help="page title (default: the script's file name)")
    return parser


def write_view(args) -> int:
    try:
        events = read_script(args.script)
        title = args.title or f"Order book replay: {Path(args.script).name}"
        page = render_html(build_view(events, depth=args.depth, title=title[:200]))
    except (ScriptError, ViewError) as exc:
        print(f"mmp: {args.script} can't be viewed:\n{exc}", file=sys.stderr)
        return EXIT_SCRIPT
    except InvariantError as exc:
        print(f"mmp: internal error, the engine is inconsistent after the replay:\n{exc}", file=sys.stderr)
        return EXIT_BUG
    output = Path(args.output) if args.output else Path(Path(args.script).stem + ".html")
    try:
        output.write_text(page, encoding="utf-8")
    except OSError as exc:
        print(f"mmp: can't write {output}: {exc.strerror}", file=sys.stderr)
        return EXIT_SCRIPT
    print(f"wrote {output} ({len(events)} events); open it in a browser")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "view":
        return write_view(args)
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
