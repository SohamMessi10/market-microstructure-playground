import json
import re
from pathlib import Path

import pytest

from microstructure import MatchingEngine, Side
from microstructure.cli import EXIT_OK, EXIT_SCRIPT, main
from microstructure.replay import parse_script, read_script
from microstructure.view import MAX_SEGMENTS, MAX_VIEW_EVENTS, ViewError, build_view, outcome, render_html

ROOT = Path(__file__).resolve().parent.parent


def segs(row):
    return [(s["id"], s["qty"], s["kind"]) for s in row["segments"]]


def script(*lines):
    return parse_script([json.dumps(line) for line in lines])


def order(side, price, quantity, **extra):
    return {"type": "order", "side": side, "price": price, "quantity": quantity, **extra}


def test_walkthrough_sweep_step_shows_what_left_each_queue():
    step = build_view(read_script(ROOT / "examples" / "walkthrough.jsonl"))["steps"][4]  # buy 10 @ 102
    assert step["headline"] == "Buy 10 at 102"
    assert step["outcome"] == "Filled in 3 trades at an average price of 101.2."
    assert [(r["price"], r["quantity"], segs(r)) for r in step["asks"]] == [
        (102, 2, [(3, 2, "gone"), (3, 2, "live")]),    # front of order 3 traded, the rest still waits
        (101, 0, [(1, 5, "gone"), (2, 3, "gone")]),    # emptied level, shown once more
    ]
    assert [(r["price"], segs(r)) for r in step["bids"]] == [(100, [(4, 6, "live")])]
    assert [(t["quantity"], t["price"], t["buy"], t["sell"]) for t in step["trades"]] == \
        [(5, 101, 5, 1), (3, 101, 5, 2), (2, 102, 5, 3)]
    assert (step["best_bid"], step["best_ask"]) == (100, 102)


def test_new_resting_order_is_marked_new_and_cancel_marks_gone():
    view = build_view(script(order("buy", 100, 5), order("buy", 100, 3), {"type": "cancel", "order_id": 1}))
    second, cancel = view["steps"][1], view["steps"][2]
    assert segs(second["bids"][0]) == [(1, 5, "live"), (2, 3, "new")]
    assert segs(cancel["bids"][0]) == [(1, 5, "gone"), (2, 3, "live")]  # exact place in the queue
    assert cancel["outcome"] == "Cancelled the 5 still resting."


def test_a_level_pushed_out_of_view_is_not_shown_as_gone():
    # Regression: with depth 2, a new better bid pushes 98 out of view. Its order is still in
    # the book, so it must not be drawn as having left. (Found in review, before any test.)
    view = build_view(script(order("buy", 98, 1), order("buy", 99, 1), order("buy", 100, 1)), depth=2)
    last = view["steps"][2]
    assert [(r["price"], segs(r)) for r in last["bids"]] == [(100, [(3, 1, "new")]), (99, [(2, 1, "live")])]


def test_many_orders_at_one_price_merge_into_one_more_segment():
    view = build_view(script(*[order("sell", 101, 1) for _ in range(MAX_SEGMENTS + 5)]))
    row = view["steps"][-1]["asks"][0]
    assert len(row["segments"]) == MAX_SEGMENTS
    assert row["segments"][-1] == {"id": None, "qty": 6, "kind": "more", "count": 6}
    assert sum(s["qty"] for s in row["segments"]) == row["quantity"] == MAX_SEGMENTS + 5


def test_outcome_wording():
    engine = MatchingEngine()
    assert outcome(engine.submit(Side.SELL, 101, 5)) == "Nothing to trade against, so all 5 rest at its limit."
    assert outcome(engine.submit(Side.SELL, 102, 3)) == "Nothing to trade against, so all 3 rest at its limit."
    assert outcome(engine.submit(Side.BUY, 101, 2)) == "Filled in 1 trade at 101."   # #1 has 3 left
    # 3 at 101, then 2 at 102: (303 + 204) / 5 = 101.4
    assert outcome(engine.submit(Side.BUY, 102, 5)) == "Filled in 2 trades at an average price of 101.4."
    assert outcome(engine.submit(Side.BUY, 102, 9)) == "Traded 1 in 1 trade; the other 8 rest at its limit."
    assert outcome(engine.submit(Side.SELL, 99, 10)) == "Traded 8 in 1 trade; the other 2 rest at its limit."
    assert outcome(engine.cancel(99)) == "Refused: there is no order 99."


def test_average_is_not_rounded_away():
    view = build_view(read_script(ROOT / "examples" / "queue_priority.jsonl"))
    assert view["steps"][3]["outcome"] == "Filled in 2 trades at an average price of 100.625."


def test_limits():
    with pytest.raises(ViewError, match="up to"):
        build_view(script(*[order("buy", 100, 1)] * (MAX_VIEW_EVENTS + 1)))
    for depth in (0, 21):
        with pytest.raises(ViewError, match="depth"):
            build_view([], depth=depth)


HOSTILE = '</script><script>alert(1)</script><!-- &   "quotes"'


def embedded(page):
    match = re.search(r'<script type="application/json" id="replay-data">(.*?)</script>', page, re.S)
    return json.loads(match.group(1))


def test_script_text_cannot_break_out_of_the_page():
    view = build_view(script(order("buy", 100, 5, trader="<b>ana</b>", note=HOSTILE)), title="<i>t</i> & co")
    page = render_html(view)
    data_part = page.split('id="replay-data">', 1)[1].split("</script>", 1)[0]
    assert "<" not in data_part and ">" not in data_part and "&" not in data_part and " " not in data_part
    assert embedded(page) == view  # escaping doesn't change the data once parsed
    assert "<title>&lt;i&gt;t&lt;/i&gt; &amp; co</title>" in page
    assert page.count("<script") == 2  # the data block and the page's own script, nothing injected


def test_page_loads_nothing_from_outside():
    page = render_html(build_view([]))
    assert "default-src 'none'" in page
    assert not re.search(r'(src|href)="(https?:)?//', page)


@pytest.mark.parametrize("name", ["walkthrough", "queue_priority"])
def test_demo_pages_are_up_to_date(name):
    # docs/demo holds the generated pages for the examples. If this fails, regenerate them:
    #   mmp view examples/NAME.jsonl -o docs/demo/NAME.html
    page = render_html(build_view(read_script(ROOT / "examples" / f"{name}.jsonl"),
                                  title=f"Order book replay: {name}.jsonl"))
    assert (ROOT / "docs" / "demo" / f"{name}.html").read_text(encoding="utf-8") == page


# --- mmp view ---------------------------------------------------------------------------

def test_view_command_writes_a_page_named_after_the_script(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["view", str(ROOT / "examples" / "walkthrough.jsonl")]) == EXIT_OK
    assert "wrote walkthrough.html (9 events)" in capsys.readouterr().out
    page = (tmp_path / "walkthrough.html").read_text(encoding="utf-8")
    assert len(embedded(page)["steps"]) == 9


def test_view_command_options(tmp_path):
    out = tmp_path / "page.html"
    assert main(["view", str(ROOT / "examples" / "walkthrough.jsonl"), "-o", str(out),
                 "--depth", "3", "--title", "Class demo"]) == EXIT_OK
    data = embedded(out.read_text(encoding="utf-8"))
    assert (data["title"], data["depth"]) == ("Class demo", 3)


def test_view_command_refuses_a_bad_script_and_writes_nothing(capsys, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "order"}\n')
    out = tmp_path / "page.html"
    assert main(["view", str(bad), "-o", str(out)]) == EXIT_SCRIPT
    assert "line 1: order is missing" in capsys.readouterr().err
    assert not out.exists()


def test_view_command_reports_an_unwritable_output(capsys, tmp_path):
    assert main(["view", str(ROOT / "examples" / "walkthrough.jsonl"), "-o", str(tmp_path)]) == EXIT_SCRIPT
    assert "can't write" in capsys.readouterr().err


def test_view_command_reports_a_script_too_long_to_view(capsys, tmp_path):
    long = tmp_path / "long.jsonl"
    long.write_text((json.dumps(order("buy", 100, 1)) + "\n") * (MAX_VIEW_EVENTS + 1))
    assert main(["view", str(long), "-o", str(tmp_path / "x.html")]) == EXIT_SCRIPT
    assert "handles up to" in capsys.readouterr().err
