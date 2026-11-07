import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from microstructure import MatchingEngine, Side
from microstructure.replay import (
    CancelEvent, OrderEvent, ScriptError, describe_result, format_json, format_text, parse_line, parse_script,
    read_script, replay,
)
from microstructure.models import OrderError


def test_parses_orders_and_cancels():
    assert parse_line('{"type": "order", "side": "buy", "price": 100, "quantity": 5}', 3) == \
        OrderEvent(3, Side.BUY, 100, 5)
    assert parse_line('{"type": "order", "side": "sell", "price": 1, "quantity": 2, "trader": "ana", "note": "hi"}', 1) == \
        OrderEvent(1, Side.SELL, 1, 2, "ana", "hi")
    assert parse_line('{"type": "cancel", "order_id": 4, "note": "late"}', 9) == CancelEvent(9, 4, "late")


@pytest.mark.parametrize("text", ["", "   ", "# a comment", "   # indented comment"])
def test_blank_and_comment_lines_are_skipped(text):
    assert parse_line(text, 1) is None


@pytest.mark.parametrize("text,message", [
    ("{not json", "not valid JSON"),
    ("[1, 2]", "JSON object"),
    ('"order"', "JSON object"),
    ('{"type": "modify", "order_id": 1}', '"type" must be "order" or "cancel"'),
    ('{"side": "buy", "price": 1, "quantity": 1}', '"type" must be'),
    ('{"type": "order", "side": "buy", "price": 100}', "missing quantity"),
    ('{"type": "order", "side": "buy", "price": 100, "quantity": 5, "qty": 5}', "unknown field qty"),
    ('{"type": "order", "side": "BUY", "price": 100, "quantity": 5}', 'side must be "buy" or "sell"'),
    ('{"type": "order", "side": ["buy"], "price": 100, "quantity": 5}', 'side must be'),
    ('{"type": "order", "side": "buy", "price": 100.5, "quantity": 5}', "price must be a whole number"),
    ('{"type": "order", "side": "buy", "price": 100.0, "quantity": 5}', "price must be a whole number"),
    ('{"type": "order", "side": "buy", "price": "100", "quantity": 5}', "price must be a whole number"),
    ('{"type": "order", "side": "buy", "price": 0, "quantity": 5}', "price must be between"),
    ('{"type": "order", "side": "buy", "price": 100, "quantity": true}', "quantity must be a whole number"),
    ('{"type": "order", "side": "buy", "price": 100, "quantity": -1}', "quantity must be between"),
    ('{"type": "order", "side": "buy", "price": 100, "quantity": 5, "trader": 7}', "trader must be text"),
    ('{"type": "order", "side": "buy", "price": 100, "quantity": 5, "trader": "' + "x" * 51 + '"}', "trader must be text"),
    ('{"type": "cancel", "order_id": "3"}', "order_id must be a whole number"),
    ('{"type": "cancel", "order_id": 0}', "order_id must be at least 1"),
    ('{"type": "cancel", "order_id": 1, "note": "' + "x" * 201 + '"}', "note must be text"),
    ('{"type": "cancel", "order_id": 1, "price": 5}', "unknown field price"),
    ('{"type": "cancel", "order_id": 1, "note": "' + "x" * 10_000 + '"}', "longer than"),
    ('{"type": "order", "side": "buy", "price": NaN, "quantity": 5}', "price must be a whole number"),
])
def test_bad_lines_are_explained(text, message):
    with pytest.raises(OrderError, match=message):
        parse_line(text, 1)


def test_a_script_with_errors_lists_every_bad_line_and_runs_nothing():
    lines = [
        '{"type": "order", "side": "buy", "price": 100, "quantity": 5}',
        "# fine",
        '{"type": "order", "side": "buy", "price": 100.5, "quantity": 5}',
        '{"type": "cancel"}',
    ]
    with pytest.raises(ScriptError) as caught:
        parse_script(lines)
    assert caught.value.problems == [
        "line 3: price must be a whole number, got 100.5",
        "line 4: cancel is missing order_id",
    ]


def test_long_error_lists_are_shortened():
    with pytest.raises(ScriptError) as caught:
        parse_script(["oops"] * 25)
    assert len(caught.value.problems) == 25
    assert str(caught.value).splitlines()[-1] == "... and 5 more"


def test_read_script_reports_file_problems(tmp_path):
    with pytest.raises(ScriptError, match="no such file"):
        read_script(tmp_path / "missing.jsonl")
    with pytest.raises(ScriptError, match="is a folder"):
        read_script(tmp_path)
    binary = tmp_path / "bad.jsonl"
    binary.write_bytes(b"\xff\xfe\x00not text")
    with pytest.raises(ScriptError, match="not UTF-8"):
        read_script(binary)


def test_read_script_accepts_a_byte_order_mark_and_windows_line_endings(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b'\xef\xbb\xbf{"type": "order", "side": "buy", "price": 100, "quantity": 5}\r\n'
                     b'{"type": "cancel", "order_id": 1}\r\n')
    assert read_script(path) == [OrderEvent(1, Side.BUY, 100, 5), CancelEvent(2, 1)]


def test_empty_script_replays_to_an_empty_book():
    engine, steps = replay(parse_script([]))
    assert steps == [] and len(engine.book) == 0
    assert format_json(steps) == ""
    assert "0 orders, 0 cancels (0 refused), 0 trades, 0 traded" in format_text(engine, steps)
    assert "(empty)" in format_text(engine, steps)


def test_describe_result_covers_every_outcome():
    engine = MatchingEngine()
    assert describe_result(engine.submit(Side.SELL, 101, 5)) == "rests 5"
    assert describe_result(engine.submit(Side.BUY, 101, 2)) == "filled (2 @ 101 with #1)"
    assert describe_result(engine.submit(Side.BUY, 101, 5)) == "traded 3 (3 @ 101 with #1), rests 2"
    assert describe_result(engine.cancel(3)) == "cancelled 2"
    assert describe_result(engine.cancel(3)) == "refused: order 3 was already cancelled"


def test_text_output_shows_the_spread_between_asks_and_bids():
    engine, steps = replay(parse_script([
        '{"type": "order", "side": "buy", "price": 98, "quantity": 1}',
        '{"type": "order", "side": "buy", "price": 99, "quantity": 2}',
        '{"type": "order", "side": "sell", "price": 102, "quantity": 3}',
        '{"type": "order", "side": "sell", "price": 103, "quantity": 4}',
        '{"type": "order", "side": "sell", "price": 103, "quantity": 1}',
    ]))
    # Like a ladder: highest price at the top, so the best ask and best bid meet in the middle.
    assert format_text(engine, steps, depth=2).splitlines()[-5:] == [
        "  ask    103       5  (2 orders)",
        "  ask    102       3  (1 order)",
        "      spread 3",
        "  bid     99       2  (1 order)",
        "  bid     98       1  (1 order)",
    ]
    assert format_text(engine, steps, depth=1).splitlines()[-3:] == [
        "  ask    102       3  (1 order)", "      spread 3", "  bid     99       2  (1 order)"]


# --- replaying a script is the same as calling the engine directly ----------------------

event_specs = st.lists(
    st.one_of(
        st.tuples(st.just("order"), st.sampled_from(["buy", "sell"]), st.integers(95, 105),
                  st.integers(1, 20) | st.integers(50, 200)),
        st.tuples(st.just("cancel"), st.integers(1, 40)),
    ),
    max_size=60,
)


def as_script(specs):
    lines = []
    for spec in specs:
        if spec[0] == "order":
            lines.append(json.dumps({"type": "order", "side": spec[1], "price": spec[2], "quantity": spec[3]}))
        else:
            lines.append(json.dumps({"type": "cancel", "order_id": spec[1]}))
    return lines


@given(event_specs)
def test_replay_matches_direct_engine_calls(specs):
    engine, steps = replay(parse_script(as_script(specs)))
    direct = MatchingEngine()
    for spec, step in zip(specs, steps, strict=True):
        if spec[0] == "order":
            expected = direct.submit(Side(spec[1]), spec[2], spec[3])
        else:
            expected = direct.cancel(spec[1])
        assert step.result == expected
        assert (step.best_bid, step.best_ask) == (direct.book.best_bid(), direct.book.best_ask())
    assert engine.trades == direct.trades
    engine.check()


@given(event_specs)
def test_replaying_twice_gives_identical_output(specs):
    lines = as_script(specs)
    first, second = replay(parse_script(lines)), replay(parse_script(lines))
    assert format_json(first[1]) == format_json(second[1])
    assert format_text(*first) == format_text(*second)


@given(event_specs)
def test_json_output_is_one_valid_object_per_event(specs):
    _, steps = replay(parse_script(as_script(specs)))
    lines = format_json(steps).splitlines()
    assert len(lines) == len(steps)
    for line, step in zip(lines, steps):
        data = json.loads(line)
        assert data["line"] == step.event.line and data["order_id"] == step.result.order_id
