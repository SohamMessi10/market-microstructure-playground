"""Scripted replay: read orders and cancels from a file, run them through the engine in order.

A script is JSON Lines, one event per line:

    {"type": "order", "side": "sell", "price": 101, "quantity": 5}
    {"type": "order", "side": "buy", "price": 102, "quantity": 10, "trader": "ana"}
    {"type": "cancel", "order_id": 3, "note": "too slow: it already traded"}

Blank lines and lines starting with `#` are skipped, so scripts can explain themselves.
Order ids are not written in the script: the engine numbers orders 1, 2, 3, ... in the
order they appear, which is what a cancel refers to.

Parsing is strict and happens before anything runs. A misspelled field, a price of 101.5,
or `"quantity": true` is an error naming its line, and a script with any error doesn't run
at all, so a replay never stops halfway through.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from microstructure.engine import MAX_TRADER_LENGTH, CancelResult, MatchingEngine, SubmitResult
from microstructure.models import OrderError, Side, check_price, check_quantity

MAX_LINE_LENGTH = 10_000
MAX_NOTE_LENGTH = 200
MAX_ERRORS_SHOWN = 20


class ScriptError(ValueError):
    """The script can't be replayed. `problems` lists each one as "line N: ..."."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = problems[:MAX_ERRORS_SHOWN]
        more = len(problems) - len(shown)
        super().__init__("\n".join(shown + ([f"... and {more} more"] if more else [])))


@dataclass(frozen=True, slots=True)
class OrderEvent:
    line: int
    side: Side
    price: int
    quantity: int
    trader: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class CancelEvent:
    line: int
    order_id: int
    note: str = ""


Event = OrderEvent | CancelEvent

_FIELDS = {
    "order": ({"type", "side", "price", "quantity"}, {"trader", "note"}),
    "cancel": ({"type", "order_id"}, {"note"}),
}


def _whole_number(value: object, name: str) -> int:
    # JSON 101.0 arrives as a float and true as a bool; neither is a whole number of ticks here.
    if isinstance(value, bool) or not isinstance(value, int):
        raise OrderError(f"{name} must be a whole number, got {json.dumps(value)}")
    return value


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise OrderError(f"{name} must be text of at most {limit} characters")
    return value


def parse_line(text: str, line: int) -> Event | None:
    """One line of a script: an event, or None for a blank or comment line."""
    stripped = text.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if len(stripped) > MAX_LINE_LENGTH:
        raise OrderError(f"line is longer than {MAX_LINE_LENGTH} characters")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise OrderError(f"not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise OrderError('each line must be a JSON object like {"type": "order", ...}')
    kind = data.get("type")
    if kind not in _FIELDS:
        raise OrderError(f'"type" must be "order" or "cancel", got {json.dumps(kind)}')
    required, optional = _FIELDS[kind]
    if missing := sorted(required - data.keys()):
        raise OrderError(f"{kind} is missing {', '.join(missing)}")
    if unknown := sorted(data.keys() - required - optional):
        raise OrderError(f"{kind} has unknown field {', '.join(unknown)}")
    note = _text(data.get("note", ""), "note", MAX_NOTE_LENGTH)

    if kind == "cancel":
        order_id = _whole_number(data["order_id"], "order_id")
        if order_id < 1:
            raise OrderError(f"order_id must be at least 1, got {order_id}")
        return CancelEvent(line, order_id, note)
    try:
        side = Side(data["side"])
    except (ValueError, TypeError):
        raise OrderError(f'side must be "buy" or "sell", got {json.dumps(data["side"])}') from None
    price = check_price(_whole_number(data["price"], "price"))
    quantity = check_quantity(_whole_number(data["quantity"], "quantity"))
    trader = _text(data.get("trader", ""), "trader", MAX_TRADER_LENGTH)
    return OrderEvent(line, side, price, quantity, trader, note)


def parse_script(lines: Iterable[str]) -> list[Event]:
    """Every event in a script, or a ScriptError listing every bad line."""
    events, problems = [], []
    for number, text in enumerate(lines, start=1):
        try:
            event = parse_line(text, number)
        except OrderError as exc:
            problems.append(f"line {number}: {exc}")
            continue
        if event is not None:
            events.append(event)
    if problems:
        raise ScriptError(problems)
    return events


def read_script(path: str | Path) -> list[Event]:
    """Read and parse a script file. Raises ScriptError for a missing or unreadable file too."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ScriptError([f"{path}: no such file"]) from None
    except IsADirectoryError:
        raise ScriptError([f"{path}: is a folder, not a script file"]) from None
    except UnicodeDecodeError:
        raise ScriptError([f"{path}: not UTF-8 text"]) from None
    except OSError as exc:
        raise ScriptError([f"{path}: can't be read ({exc.strerror})"]) from None
    return parse_script(text.splitlines())


@dataclass(frozen=True, slots=True)
class Step:
    """One replayed event, what happened, and the best prices just afterwards."""

    event: Event
    result: SubmitResult | CancelResult
    best_bid: int | None
    best_ask: int | None


def replay(events: Iterable[Event], engine: MatchingEngine | None = None) -> tuple[MatchingEngine, list[Step]]:
    """Run events through an engine (a new one by default). The same events always give the same steps."""
    engine = engine or MatchingEngine()
    steps = []
    for event in events:
        if isinstance(event, OrderEvent):
            result = engine.submit(event.side, event.price, event.quantity, event.trader)
        else:
            result = engine.cancel(event.order_id)
        steps.append(Step(event, result, engine.book.best_bid(), engine.book.best_ask()))
    return engine, steps


# --- output ------------------------------------------------------------------------


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _price(value: int | None) -> str:
    return "-" if value is None else str(value)


def describe_event(event: Event) -> str:
    if isinstance(event, CancelEvent):
        return f"cancel #{event.order_id}"
    who = f" ({event.trader})" if event.trader else ""
    return f"{event.side.value} {event.quantity} @ {event.price}{who}"


def describe_result(result: SubmitResult | CancelResult) -> str:
    if isinstance(result, CancelResult):
        return f"cancelled {result.cancelled}" if result.ok else f"refused: {result.reason}"
    trades = ", ".join(f"{t.quantity} @ {t.price} with #{t.resting_order_id}" for t in result.trades)
    if not result.trades:
        return f"rests {result.resting}"
    if result.resting:
        return f"traded {result.filled} ({trades}), rests {result.resting}"
    return f"filled ({trades})"


def format_text(engine: MatchingEngine, steps: list[Step], depth: int = 5) -> str:
    """A readable log: one line per event, then a summary and the final book."""
    out = [f"{'line':>4}  {'order':>5}  {'event':<24}  {'bid / ask':<11}  result"]
    for step in steps:
        order_id = step.result.order_id
        book = f"{_price(step.best_bid)} / {_price(step.best_ask)}"
        out.append(f"{step.event.line:>4}  {'#' + str(order_id):>5}  {describe_event(step.event):<24}  "
                   f"{book:<11}  {describe_result(step.result)}")
        if step.event.note:
            out.append(f"{'':>4}  {'':>5}  note: {step.event.note}")

    orders = sum(isinstance(s.event, OrderEvent) for s in steps)
    cancels = [s.result for s in steps if isinstance(s.result, CancelResult)]
    refused = sum(not c.ok for c in cancels)
    volume = sum(t.quantity for t in engine.trades)
    out.append("")
    out.append(f"{_count(orders, 'order')}, {_count(len(cancels), 'cancel')} ({refused} refused), "
               f"{_count(len(engine.trades), 'trade')}, {volume} traded")
    out.append("final book:")
    asks = engine.book.depth(Side.SELL, depth)
    bids = engine.book.depth(Side.BUY, depth)
    if not asks and not bids:
        out.append("  (empty)")
    for level in reversed(asks):  # highest ask at the top, so the spread sits in the middle
        out.append(f"  ask {level.price:>6}  {level.quantity:>6}  ({_count(level.orders, 'order')})")
    if asks and bids:
        out.append(f"  {'spread ' + str(engine.book.spread()):>12}")
    for level in bids:
        out.append(f"  bid {level.price:>6}  {level.quantity:>6}  ({_count(level.orders, 'order')})")
    return "\n".join(out) + "\n"


def step_json(step: Step) -> dict:
    event, result = step.event, step.result
    out: dict = {"line": event.line, "order_id": result.order_id}
    if isinstance(event, OrderEvent):
        out |= {"type": "order", "side": event.side.value, "price": event.price, "quantity": event.quantity,
                "status": result.status.value, "filled": result.filled, "resting": result.resting,
                "trades": [{"trade_id": t.trade_id, "price": t.price, "quantity": t.quantity,
                            "buy_order_id": t.buy_order_id, "sell_order_id": t.sell_order_id}
                           for t in result.trades]}
        if event.trader:
            out["trader"] = event.trader
    else:
        out |= {"type": "cancel", "cancelled": result.cancelled}
        if not result.ok:
            out["refused"] = result.reason
    if event.note:
        out["note"] = event.note
    out |= {"best_bid": step.best_bid, "best_ask": step.best_ask}
    return out


def format_json(steps: list[Step]) -> str:
    """JSON Lines, one object per event, for other programs to read."""
    return "".join(json.dumps(step_json(s)) + "\n" for s in steps)
