"""Render representative EPUB pages and validate their two-column layout."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from viscount_aligner.paths import (
    ALIGNMENT_PATH,
    EPUB_PATH,
    SCREENSHOTS_DIR,
    WORK_DIR,
)


PREVIEW_ROOT = WORK_DIR / "epub-preview"
CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def verify_page(page, expected_rows: int, minimum_cell_width: int) -> None:
    assert page.locator("table.parallel-text tbody tr").count() == expected_rows
    assert page.locator("script, input, button, select").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    italian = page.locator("tbody tr td.italian").first.bounding_box()
    english = page.locator("tbody tr td.english").first.bounding_box()
    assert italian and english
    assert abs(italian["y"] - english["y"]) < 1
    assert italian["width"] >= minimum_cell_width
    assert english["width"] >= minimum_cell_width
    assert english["x"] >= italian["x"] + italian["width"] - 1


def main() -> None:
    """Render representative EPUB layouts and assert their column geometry."""
    payload = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    expected_rows = sum(unit["chapter"] == 1 for unit in payload["units"])
    if PREVIEW_ROOT.exists():
        shutil.rmtree(PREVIEW_ROOT)
    PREVIEW_ROOT.mkdir(parents=True)
    with zipfile.ZipFile(EPUB_PATH) as archive:
        archive.extractall(PREVIEW_ROOT)
    chapter_path = next(PREVIEW_ROOT.rglob("chapter-1.xhtml"))
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(CHROME_PATH),
            headless=True,
        )
        desktop = browser.new_page(viewport={"width": 900, "height": 1000})
        desktop.on("pageerror", lambda error: page_errors.append(str(error)))
        desktop.goto(chapter_path.as_uri(), wait_until="load")
        verify_page(desktop, expected_rows, 420)
        desktop.screenshot(path=SCREENSHOTS_DIR / "epub-wide.png", full_page=False)

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.on("pageerror", lambda error: page_errors.append(str(error)))
        mobile.goto(chapter_path.as_uri(), wait_until="load")
        verify_page(mobile, expected_rows, 180)
        mobile.screenshot(path=SCREENSHOTS_DIR / "epub-narrow.png", full_page=False)
        browser.close()

    assert not page_errors, page_errors
    print(
        json.dumps(
            {
                "epub": str(EPUB_PATH),
                "chapter_1_rows": expected_rows,
                "wide_viewport": "900x1000",
                "narrow_viewport": "390x844",
                "page_errors": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
