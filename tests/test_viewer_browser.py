"""The replay page in a real browser (Chromium, through Playwright).

Optional: these tests skip unless Playwright and its browser are installed:

    python -m pip install -e ".[dev,browser]"
    python -m playwright install chromium

CI runs them in a separate job with REQUIRE_BROWSER=1, which turns a missing browser into a
failure instead of a skip, so the job can't pass by silently testing nothing.
"""

import json
import os
from pathlib import Path

import pytest

REQUIRED = os.environ.get("REQUIRE_BROWSER") == "1"
if REQUIRED:
    import playwright.sync_api as sync_api
else:
    sync_api = pytest.importorskip("playwright.sync_api")

from microstructure.replay import parse_script, read_script  # noqa: E402
from microstructure.view import build_view, render_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except Exception as exc:  # the package is installed but its browser isn't
            if REQUIRED:
                raise
            pytest.skip(f"Chromium isn't available: {exc}")
        yield chromium
        chromium.close()


@pytest.fixture
def open_page(browser, tmp_path):
    contexts = []

    def opener(events, *, step=None, width=1200, scheme="light", title="Test replay"):
        path = tmp_path / "replay.html"
        path.write_text(render_html(build_view(events, title=title)), encoding="utf-8")
        context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
        contexts.append(context)
        page = context.new_page()
        page.errors = []
        page.dialogs = []
        page.on("pageerror", lambda exc: page.errors.append(str(exc)))
        page.on("console", lambda msg: msg.type == "error" and page.errors.append(msg.text))
        page.on("dialog", lambda dialog: (page.dialogs.append(dialog.message), dialog.dismiss()))
        page.goto(path.as_uri() + (f"#step={step}" if step is not None else ""))
        return page

    yield opener
    for context in contexts:
        context.close()


def walkthrough():
    return read_script(ROOT / "examples" / "walkthrough.jsonl")


def text(page, selector):
    return page.locator(selector).inner_text().strip()


def test_starts_empty_and_steps_forward_and_back(open_page):
    page = open_page(walkthrough())
    assert text(page, "#headline") == "Empty book"
    assert text(page, "#step-count") == "Step 0 of 9"
    assert page.locator("#prev").is_disabled() and page.locator("#first").is_disabled()
    assert "The book is empty" in text(page, "#ladder")

    page.click("#next")
    assert text(page, "#headline") == "Sell 5 at 101"
    assert text(page, "#where") == "Script line 2, order 1"
    assert page.url.endswith("#step=1")

    for _ in range(4):
        page.click("#next")
    assert text(page, "#headline") == "Buy 10 at 102"
    assert text(page, "#outcome") == "Filled in 3 trades at an average price of 101.2."
    assert page.locator("#step-trades tbody tr").count() == 3

    page.click("#prev")
    assert text(page, "#headline") == "Buy 6 at 100"
    assert page.errors == []


def test_the_ladder_shows_the_queue_and_what_left_it(open_page):
    page = open_page(walkthrough(), step=5)
    rows = page.locator("#ladder .row")
    assert rows.count() == 3
    assert [rows.nth(i).locator(".price").inner_text().split()[-1] for i in range(3)] == ["102", "101", "100"]
    assert [rows.nth(0).locator(".seg").nth(i).get_attribute("class") for i in range(2)] == ["seg gone", "seg live"]
    assert rows.nth(0).locator(".seg").nth(0).get_attribute("title") == "order 3: 2 traded in this step"
    assert "row ask empty" in rows.nth(1).get_attribute("class")
    assert "best" in rows.nth(0).get_attribute("class") and "best" in rows.nth(2).get_attribute("class")
    assert text(page, ".spread") == "spread 2"
    assert "Sell side at 102: 2 resting." in rows.nth(0).get_attribute("aria-label")


def test_keyboard_slider_and_deep_link(open_page):
    page = open_page(walkthrough(), step=7)
    assert text(page, "#headline") == "Cancel order 3"
    page.keyboard.press("End")
    assert text(page, "#step-count") == "Step 9 of 9"
    assert page.locator("#next").is_disabled() and page.locator("#last").is_disabled()
    page.keyboard.press("ArrowLeft")
    assert text(page, "#step-count") == "Step 8 of 9"
    page.keyboard.press("Home")
    assert text(page, "#step-count") == "Step 0 of 9"
    page.locator("#scrubber").fill("6")
    assert text(page, "#headline") == "Sell 8 at 99"
    assert text(page, "#note") == "trades at 100, better than its limit, then rests 2"
    page.keyboard.press("ArrowRight")  # with the slider focused, still exactly one step
    assert text(page, "#step-count") == "Step 7 of 9"
    assert page.locator("#scrubber").input_value() == "7"


def test_trade_log_grows_newest_first(open_page):
    page = open_page(walkthrough(), step=5)  # after the sweep: trades 1-3, not yet 4
    cells = page.locator("#log tbody tr td:first-child")
    assert [cells.nth(i).inner_text() for i in range(cells.count())] == ["#3", "#2", "#1"]
    page.keyboard.press("End")
    cells = page.locator("#log tbody tr td:first-child")
    assert [cells.nth(i).inner_text() for i in range(cells.count())] == ["#4", "#3", "#2", "#1"]
    page.keyboard.press("Home")
    assert text(page, "#log") == "No trades yet."


def test_refused_cancel_is_shown_as_refused(open_page):
    page = open_page(walkthrough(), step=8)
    assert text(page, "#outcome") == "Refused: order 3 was already cancelled."
    assert "refused" in page.locator("#outcome").get_attribute("class")
    assert page.locator("#step-trades").inner_text() == ""


def test_hostile_script_text_is_shown_as_text(open_page):
    hostile = '</script><script>alert(1)</script><img src=x onerror=alert(2)> & "q"'
    events = parse_script([json.dumps({"type": "order", "side": "buy", "price": 100, "quantity": 5,
                                       "trader": "<b>x</b>", "note": hostile})])
    page = open_page(events, step=1, title="<script>alert(3)</script>")
    assert text(page, "#note") == hostile
    assert "<b>x</b>" in text(page, "#headline")
    assert page.title() == "<script>alert(3)</script>"
    assert page.locator("img, b").count() == 0
    assert page.dialogs == [] and page.errors == []


@pytest.mark.parametrize("width", [390, 768, 1280])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_step_fits_the_screen_without_errors(open_page, width, scheme):
    for name in ("walkthrough", "queue_priority"):
        events = read_script(ROOT / "examples" / f"{name}.jsonl")
        page = open_page(events, width=width, scheme=scheme)
        for step in range(len(events) + 1):
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 0, f"{name} step {step} scrolls sideways by {overflow}px at {width}px"
            page.keyboard.press("ArrowRight")
        assert page.errors == []


def test_the_page_cannot_load_anything_from_outside(open_page):
    page = open_page([])
    # Try to load an image from elsewhere; the Content-Security-Policy must block it.
    blocked = page.evaluate("""() => new Promise((resolve) => {
        document.addEventListener("securitypolicyviolation", (e) => resolve(e.violatedDirective));
        const img = document.createElement("img");
        img.src = "https://example.com/tracker.png";
        document.body.append(img);
        setTimeout(() => resolve(null), 2000);
    })""")
    assert blocked == "img-src"


def test_empty_script(open_page):
    page = open_page([])
    assert text(page, "#step-count") == "Step 0 of 0"
    assert text(page, "#outcome") == "This replay has 0 events."
    assert page.locator("#next").is_disabled()
