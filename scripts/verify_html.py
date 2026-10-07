"""Run browser-level layout and interaction checks against the HTML reader."""

from __future__ import annotations

import json
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

from serve_reader import ReaderHandler
from viscount_aligner.paths import ALIGNMENT_PATH, HTML_PATH, SCREENSHOTS_DIR, SITE_DIR
from viscount_aligner.site import sync_web_assets


CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def assert_no_overflow(page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def main() -> None:
    """Exercise the reader at desktop and mobile breakpoints in real Chrome."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    sync_web_assets()
    alignment = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    expected_rows = alignment["summary"]["alignment_units"]
    expected_first_literal = alignment["units"][0]["literal_english_sentences"][0][
        "english"
    ]
    console_errors: list[str] = []
    page_errors: list[str] = []

    handler = partial(ReaderHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    reader_url = f"http://127.0.0.1:{server.server_port}/"

    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            executable_path=str(CHROME_PATH),
            headless=True,
        )
        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        desktop.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        desktop.on("pageerror", lambda error: page_errors.append(str(error)))
        desktop.goto(reader_url, wait_until="load")

        assert desktop.locator(".alignment-row").count() == expected_rows
        assert desktop.locator(".alignment-row .row-selector").count() == expected_rows
        assert desktop.locator("#player-dock").count() == 1
        desktop.locator("#play-segment").wait_for(state="visible")
        desktop.wait_for_function(
            "!document.querySelector('#play-segment').disabled"
        )
        desktop.wait_for_function(
            "document.querySelector('#offline-audio').textContent !== 'Checking offline audio…'"
        )
        assert desktop.locator("#offline-indicator").count() == 0
        assert desktop.locator(".alignment-row.is-current").count() == 1
        assert desktop.locator(".alignment-row.is-current").get_attribute("id") == "c01-a0001"
        assert desktop.locator("[data-audio-start]").count() == expected_rows
        assert desktop.locator(".supplement").count() == 4
        assert desktop.locator(".cover").evaluate("image => image.complete && image.naturalWidth > 0")
        assert_no_overflow(desktop)

        assert desktop.locator(".translation-published").first.is_visible()
        assert desktop.locator(".translation-literal").first.is_hidden()
        desktop.locator('.translation-controls [data-translation="literal"]').click()
        assert desktop.locator(".translation-published").first.is_hidden()
        assert desktop.locator(".translation-literal").first.is_visible()
        assert desktop.locator(".translation-literal").first.inner_text() == expected_first_literal
        # text_content checks the semantic label without CSS text-transform.
        assert desktop.locator("#translation-label").text_content() == "Literal"
        desktop.locator('.translation-controls [data-translation="published"]').click()

        first_it = desktop.locator(".alignment-row .italian").first.bounding_box()
        first_en = desktop.locator(".alignment-row .english").first.bounding_box()
        assert first_it and first_en
        assert abs(first_it["y"] - first_en["y"]) < 1
        assert first_it["width"] > 500 and first_en["width"] > 500

        desktop.locator("#search").fill("cicogne")
        visible_search_rows = desktop.locator(".alignment-row:visible").count()
        assert 0 < visible_search_rows < expected_rows
        desktop.locator("#search").fill("")
        desktop.locator("#search").fill("riding towards the Christian camp")
        assert desktop.locator(".alignment-row:visible").count() == 1
        desktop.locator("#search").fill("")
        desktop.locator("#chapter-select").select_option("10")
        desktop.wait_for_timeout(600)
        assert desktop.evaluate("window.scrollY") > 0

        before_size = desktop.locator(".sentence-cell").first.evaluate(
            "element => parseFloat(getComputedStyle(element).fontSize)"
        )
        desktop.locator("#type-up").click()
        after_size = desktop.locator(".sentence-cell").first.evaluate(
            "element => parseFloat(getComputedStyle(element).fontSize)"
        )
        assert after_size == before_size + 1

        desktop.locator("#speed-toggle").click()
        assert desktop.locator("#speed-panel").is_visible()
        desktop.locator("#speed-slider").evaluate(
            """slider => {
                slider.value = '0.72';
                slider.dispatchEvent(new Event('input', {bubbles: true}));
                slider.dispatchEvent(new Event('change', {bubbles: true}));
            }"""
        )
        assert desktop.locator("#narration").evaluate("audio => audio.playbackRate") == 0.7
        assert desktop.locator("#speed-button-value").inner_text() == "0.7×"
        desktop.locator("#speed-slider").evaluate(
            """slider => {
                slider.value = '0.76';
                slider.dispatchEvent(new Event('input', {bubbles: true}));
                slider.dispatchEvent(new Event('change', {bubbles: true}));
            }"""
        )
        assert desktop.locator("#narration").evaluate("audio => audio.playbackRate") == 0.76
        desktop.locator("#speed-slider").evaluate(
            """slider => {
                slider.value = '1';
                slider.dispatchEvent(new Event('input', {bubbles: true}));
                slider.dispatchEvent(new Event('change', {bubbles: true}));
            }"""
        )
        desktop.locator("#speed-toggle").click()
        assert desktop.locator("#speed-panel").is_hidden()

        expected_repeat_labels = ["3×", "5×", "8×", "0×"]
        for expected_label in expected_repeat_labels:
            desktop.locator("#repeat-segment").click()
            assert desktop.locator("#repeat-count").inner_text() == expected_label

        desktop.locator("#center-segment").click()
        desktop.wait_for_function(
            "document.querySelector('#c01-a0001').getBoundingClientRect().top >= 0",
            timeout=5_000,
        )
        assert desktop.locator("#c01-a0001").bounding_box()["y"] >= 0
        desktop.locator("#play-segment").click()
        desktop.wait_for_function(
            "document.querySelector('#narration').currentTime >= 0.95"
        )
        desktop.wait_for_function(
            "document.querySelector('.alignment-row.is-current').id === 'c01-a0002'",
            timeout=5_000,
        )
        assert not desktop.locator("#narration").evaluate("audio => audio.paused")
        first_transition_time = desktop.locator("#narration").evaluate(
            "audio => audio.currentTime"
        )
        assert first_transition_time >= 3.38
        desktop.locator("#play-segment").click()
        desktop.screenshot(path=SCREENSHOTS_DIR / "desktop.png", full_page=False)

        # Text is inert; only the isolated gutter control can move the saved playhead.
        desktop.locator("#c01-a0010 .italian").click()
        assert desktop.locator(".alignment-row.is-current").get_attribute("id") == "c01-a0002"
        desktop.locator('[data-select-section="c01-a0015"]').click()
        assert desktop.locator(".alignment-row.is-current").get_attribute("id") == "c01-a0015"
        assert desktop.locator("#narration").evaluate("audio => audio.paused")
        assert desktop.locator("#player-status").inner_text() == (
            "Section 15 selected · press Play"
        )
        assert desktop.evaluate(
            "JSON.parse(localStorage.getItem('viscount-audio-progress-v1')).unitId"
        ) == "c01-a0015"
        desktop.reload(wait_until="load")
        desktop.wait_for_function("!document.querySelector('#play-segment').disabled")
        assert desktop.locator(".alignment-row.is-current").get_attribute("id") == "c01-a0015"

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        mobile.on("pageerror", lambda error: page_errors.append(str(error)))
        mobile.goto(reader_url, wait_until="load")
        mobile.wait_for_function("!document.querySelector('#play-segment').disabled")
        mobile.wait_for_function(
            "document.querySelector('#offline-audio').textContent !== 'Checking offline audio…'"
        )
        assert mobile.locator("#offline-indicator").count() == 0
        assert_no_overflow(mobile)
        assert mobile.locator(".identity").evaluate(
            "element => element.getBoundingClientRect().height"
        ) <= 56
        assert mobile.locator(".toolbar").evaluate(
            "element => getComputedStyle(element).visibility"
        ) == "hidden"
        mobile_dock = mobile.locator("#player-dock").bounding_box()
        assert mobile_dock
        assert mobile_dock["width"] <= 380
        assert mobile_dock["x"] >= 0
        assert mobile_dock["x"] + mobile_dock["width"] <= 390

        mobile_it = mobile.locator(".alignment-row .italian").first.bounding_box()
        mobile_en = mobile.locator(".alignment-row .english").first.bounding_box()
        assert mobile_it and mobile_en
        assert mobile_en["y"] >= mobile_it["y"] + mobile_it["height"] - 1
        assert mobile_it["width"] > 330 and mobile_en["width"] > 330

        mobile.locator("#menu-toggle").click()
        mobile.wait_for_timeout(250)
        assert mobile.locator(".toolbar").evaluate(
            "element => getComputedStyle(element).visibility"
        ) == "visible"
        assert mobile.locator("#offline-audio").is_visible()
        assert mobile.locator("#offline-audio").inner_text() == "Save audio · 149 MB"
        mobile.screenshot(path=SCREENSHOTS_DIR / "mobile-menu.png", full_page=False)
        mobile.locator('.language-controls [data-language="en"]').click()
        assert mobile.locator(".sentence-cell.italian").first.evaluate(
            "element => getComputedStyle(element).display"
        ) == "none"
        assert mobile.locator(".sentence-cell.english").first.evaluate(
            "element => getComputedStyle(element).display"
        ) != "none"
        mobile.locator('.translation-controls [data-translation="literal"]').click()
        assert mobile.locator(".translation-published").first.is_hidden()
        assert mobile.locator(".translation-literal").first.is_visible()
        mobile.locator('.language-controls [data-language="both"]').click()
        assert mobile.locator(".sentence-cell.italian").first.is_visible()
        mobile.locator("#menu-close").click()
        mobile.wait_for_timeout(250)
        assert mobile.locator(".toolbar").evaluate(
            "element => getComputedStyle(element).visibility"
        ) == "hidden"
        mobile.locator("#next-segment").click()
        mobile.wait_for_timeout(600)
        assert mobile.locator(".alignment-row.is-current").get_attribute("id") == "c01-a0002"
        current_box = mobile.locator(".alignment-row.is-current").bounding_box()
        mobile_dock = mobile.locator("#player-dock").bounding_box()
        assert current_box and mobile_dock
        assert current_box["y"] >= 0
        assert current_box["y"] + current_box["height"] <= mobile_dock["y"]
        mobile.locator("#speed-toggle").click()
        assert mobile.locator("#speed-panel").is_visible()
        mobile.screenshot(path=SCREENSHOTS_DIR / "mobile-speed.png", full_page=False)
        mobile.locator("#speed-toggle").click()
        assert mobile.locator("#speed-panel").is_hidden()
        mobile.screenshot(path=SCREENSHOTS_DIR / "mobile.png", full_page=False)
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        server.shutdown()
        server.server_close()
        server_thread.join()

    assert not console_errors, console_errors
    assert not page_errors, page_errors
    print(
        json.dumps(
            {
                "desktop": "1440x1000",
                "mobile": "390x844",
                "rows": expected_rows,
                "supplements": 4,
                "first_auto_advance_at": round(first_transition_time, 3),
                "search_matches_for_cicogne": visible_search_rows,
                "console_errors": 0,
                "page_errors": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
