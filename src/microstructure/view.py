"""Build a self-contained HTML page that steps through a replay one event at a time.

For every event the page shows the book just after it, as a price ladder. Each price row
is a queue bar: one segment per resting order, in arrival order (front of the queue on the
left), sized by quantity. Quantity that left the book in this step, by trading or by a
cancel, stays visible as a dashed "gone" segment in its exact place, and the order that just
arrived is outlined. That makes price-time priority visible: you watch the front of the
best queue being eaten.

The page is one file with no outside requests: the replay data is embedded as JSON, and a
Content-Security-Policy forbids loading anything. Text from the script (notes, trader
names) is escaped when embedded and inserted into the page only as text, never as HTML.
"""

from __future__ import annotations

import html
import json
from importlib import resources

from microstructure.book import Book
from microstructure.engine import CancelResult, MatchingEngine
from microstructure.models import Side
from microstructure.replay import Event, OrderEvent

MAX_VIEW_EVENTS = 2000     # every step stores a book snapshot, so keep the page a sensible size
MAX_SEGMENTS = 30          # orders drawn per price level; the rest merge into one "more" segment
DEFAULT_DEPTH = 8


class ViewError(ValueError):
    """The replay can't be turned into a page."""


def _snapshot(book: Book, side: Side, depth: int) -> list[tuple[int, list[tuple[int, int]]]]:
    """The best `depth` levels: (price, [(order id, remaining), ...] in queue order)."""
    out = []
    for level in book.side(side).levels():
        if len(out) == depth:
            break
        out.append((level.price, [(o.order_id, o.remaining) for o in level]))
    return out


def _levels(before, after, book: Book, side: Side, new_order_id: int | None) -> list[dict]:
    """Merge the snapshots from before and after an event into rows of segments.

    Walk each level's queue as it was before the event: an order still there is "live"
    (plus a "gone" segment for any quantity it lost); an order no longer there is "gone".
    Orders only in the after snapshot are the one that just arrived ("new").

    Whether an order is gone is asked of the book itself, not the after snapshot: the
    snapshot only holds the best `depth` levels, so a level pushed out of view by a new,
    better price would otherwise look as if all its orders had left the book.
    """
    before_levels, after_levels = dict(before), dict(after)
    emptied = {p for p in before_levels if book.side(side).level(p) is None}
    rows = []
    for price in sorted(after_levels.keys() | emptied, reverse=True):  # highest price at the top
        segments = []
        seen = set()
        for order_id, before_qty in before_levels.get(price, []):
            resting = book.get(order_id)
            after_qty = resting.remaining if resting else 0
            seen.add(order_id)
            if before_qty > after_qty:
                segments.append({"id": order_id, "qty": before_qty - after_qty, "kind": "gone"})
            if after_qty:
                segments.append({"id": order_id, "qty": after_qty, "kind": "live"})
        for order_id, qty in after_levels.get(price, []):
            if order_id not in seen:  # wasn't visible before: just arrived, or newly in view
                segments.append({"id": order_id, "qty": qty, "kind": "new" if order_id == new_order_id else "live"})
        if len(segments) > MAX_SEGMENTS:
            rest = segments[MAX_SEGMENTS - 1:]
            segments = segments[:MAX_SEGMENTS - 1] + [{
                "id": None, "qty": sum(x["qty"] for x in rest), "kind": "more", "count": len(rest)}]
        rows.append({
            "price": price,
            "quantity": sum(q for _, q in after_levels.get(price, [])),
            "segments": segments,
        })
    return rows


def headline(event: Event) -> str:
    if isinstance(event, OrderEvent):
        return f"{event.side.value.capitalize()} {event.quantity} at {event.price}"
    return f"Cancel order {event.order_id}"


def outcome(result) -> str:
    if isinstance(result, CancelResult):
        if result.ok:
            return f"Cancelled the {result.cancelled} still resting."
        return f"Refused: {result.reason}."
    if not result.trades:
        return f"Nothing to trade against, so all {result.resting} rest at its limit."
    trades = len(result.trades)
    in_trades = f"in {trades} trade{'s' * (trades != 1)}"
    if result.resting:
        return f"Traded {result.filled} {in_trades}; the other {result.resting} rest at its limit."
    if trades == 1:
        return f"Filled in 1 trade at {result.trades[0].price}."
    average = result.average_price
    shown = f"{average:.4f}".rstrip("0").rstrip(".")  # 805/8 is 100.625; two places would round it
    return f"Filled {in_trades} at an average price of {shown}."


def build_view(events: list[Event], *, depth: int = DEFAULT_DEPTH, title: str = "") -> dict:
    """Replay the events and capture what the page needs for every step."""
    if len(events) > MAX_VIEW_EVENTS:
        raise ViewError(f"the script has {len(events)} events; the viewer handles up to {MAX_VIEW_EVENTS}")
    if not 1 <= depth <= 20:
        raise ViewError(f"depth must be between 1 and 20, got {depth}")
    engine = MatchingEngine()
    steps = []
    for event in events:
        before = {s: _snapshot(engine.book, s, depth) for s in Side}
        if isinstance(event, OrderEvent):
            result = engine.submit(event.side, event.price, event.quantity, event.trader)
        else:
            result = engine.cancel(event.order_id)
        after = {s: _snapshot(engine.book, s, depth) for s in Side}
        new_id = result.order_id if isinstance(event, OrderEvent) and result.resting else None
        step = {
            "line": event.line,
            "order_id": result.order_id,
            "kind": "order" if isinstance(event, OrderEvent) else "cancel",
            "headline": headline(event),
            "outcome": outcome(result),
            "ok": not isinstance(result, CancelResult) or result.ok,
            "note": event.note,
            "trades": [{"id": t.trade_id, "price": t.price, "quantity": t.quantity,
                        "buy": t.buy_order_id, "sell": t.sell_order_id}
                       for t in getattr(result, "trades", ())],
            "best_bid": engine.book.best_bid(),
            "best_ask": engine.book.best_ask(),
            "asks": _levels(before[Side.SELL], after[Side.SELL], engine.book, Side.SELL, new_id),
            "bids": _levels(before[Side.BUY], after[Side.BUY], engine.book, Side.BUY, new_id),
        }
        if isinstance(event, OrderEvent):
            step |= {"side": event.side.value, "price": event.price, "quantity": event.quantity,
                     "trader": event.trader}
        steps.append(step)
    engine.check()
    return {"title": title, "depth": depth, "steps": steps}


def _embed(data: dict) -> str:
    """JSON that is safe inside <script type="application/json">.

    A note containing "</script>" would otherwise end the script element early and let the
    rest be read as HTML. Escaping <, > and & as \\u003c etc. keeps the JSON identical once
    parsed, while the HTML parser never sees a tag. U+2028/2029 are escaped for old parsers.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for char, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                         (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(char, escape)
    return text


def render_html(data: dict) -> str:
    template = resources.files("microstructure").joinpath("templates/viewer.html").read_text(encoding="utf-8")
    title = data["title"] or "Order book replay"
    return (template
            .replace("__PAGE_TITLE__", html.escape(title))
            .replace("__REPLAY_DATA__", _embed(data)))
