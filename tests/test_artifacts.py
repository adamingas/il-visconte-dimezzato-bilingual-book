from __future__ import annotations

import json
from pathlib import Path
import zipfile

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from viscount_aligner.paths import (
    ALIGNMENT_PATH,
    AUDIO_ALIGNMENT_PATH,
    EPUB_PATH,
    HTML_PATH,
    WEB_DIR,
)
from viscount_aligner.sources import SOURCES, extract_source


SERVICE_WORKER_PATH = WEB_DIR / "service-worker.js"
MANIFEST_PATH = WEB_DIR / "manifest.webmanifest"


def test_all_sources_contain_the_ten_chapter_story() -> None:
    for spec in SOURCES.values():
        chapters = extract_source(spec)
        assert [chapter.number for chapter in chapters] == list(range(1, 11))
        assert all(chapter.paragraphs for chapter in chapters)
        assert all(chapter.sentences for chapter in chapters)
        assert all(sentence.text != "(1951)" for chapter in chapters for sentence in chapter.sentences)


def test_alignment_covers_every_source_sentence_once_in_order() -> None:
    payload = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    italian = extract_source(SOURCES[payload["sources"]["italian"]["key"]])
    english = extract_source(SOURCES[payload["sources"]["english"]["key"]])

    expected_it = [sentence.id for chapter in italian for sentence in chapter.sentences]
    expected_en = [sentence.id for chapter in english for sentence in chapter.sentences]
    actual_it = [sentence_id for unit in payload["units"] for sentence_id in unit["italian_ids"]]
    actual_en = [
        sentence_id
        for unit in payload["units"]
        for sentence_id in unit["english_ids"]
        if not sentence_id.startswith("supplement-")
    ]

    assert actual_it == expected_it
    assert actual_en == expected_en
    assert all(unit["italian"] and unit["english"] for unit in payload["units"])
    assert sum(unit["confidence"] == "supplemental" for unit in payload["units"]) == 4

    literal_pairs = [
        pair for unit in payload["units"] for pair in unit["literal_english_sentences"]
    ]
    assert [pair["italian_id"] for pair in literal_pairs] == expected_it
    assert [pair["italian"] for pair in literal_pairs] == [
        sentence.text for chapter in italian for sentence in chapter.sentences
    ]
    assert all(pair["english"].strip() for pair in literal_pairs)
    assert payload["literal_translation"]["sentence_count"] == len(expected_it)
    assert payload["literal_translation"]["prompt_version"] >= 1


def test_html_is_complete_and_self_contained() -> None:
    payload = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    audio_payload = json.loads(AUDIO_ALIGNMENT_PATH.read_text(encoding="utf-8"))
    soup = BeautifulSoup(HTML_PATH.read_text(encoding="utf-8"), "html.parser")

    rows = soup.select(".alignment-row")
    assert len(rows) == payload["summary"]["alignment_units"]
    assert len(soup.select(".chapter")) == 10
    assert all(row.select_one(".italian p") for row in rows)
    assert all(row.select_one(".translation-published p") for row in rows)
    assert all(row.select_one(".translation-literal p") for row in rows)
    assert len(soup.select(".translation-controls [data-translation]")) == 2
    assert soup.select_one(".cover")["src"].startswith("data:image/")
    assert not soup.select('[src^="http"], [href^="http"]')
    assert soup.select_one("#search") is not None
    assert soup.select_one("#chapter-select") is not None
    assert [row["id"] for row in rows] == [unit["id"] for unit in audio_payload["units"]]
    selectors = soup.select(".alignment-row .row-selector[data-select-section]")
    assert len(selectors) == len(rows)
    assert [button["data-select-section"] for button in selectors] == [
        row["id"] for row in rows
    ]
    assert soup.select_one("#player-dock") is not None
    assert soup.select_one("#play-segment") is not None
    assert soup.select_one("#previous-segment") is not None
    assert soup.select_one("#next-segment") is not None
    assert soup.select_one("#repeat-segment") is not None
    assert soup.select_one("#center-segment") is not None
    assert soup.select_one("#speed-toggle") is not None
    speed_slider = soup.select_one("#speed-slider")
    assert speed_slider["min"] == "0.5"
    assert speed_slider["max"] == "1.2"
    assert speed_slider["step"] == "0.01"
    assert [option["value"] for option in soup.select("#speed-anchors option")] == [
        "0.5",
        "0.7",
        "0.9",
        "1",
        "1.2",
    ]
    assert soup.select_one("#narration") is not None
    assert soup.select_one('link[rel="manifest"]')["href"] == "manifest.webmanifest"
    script = soup.select_one("script").get_text()
    assert "advanceAfterCurrent" in script
    assert "viscount-audio-progress-v1" in script
    assert "viscount-repeat-count" in script
    assert "player.addEventListener('ended', checkSegmentEnd)" in script


def test_offline_reader_assets_are_present() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    service_worker = SERVICE_WORKER_PATH.read_text(encoding="utf-8")

    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./"
    assert manifest["icons"][0]["src"] == "app-icon.svg"
    assert "viscount-audio-alignment.json" in service_worker
    assert "il_visconte_dimezzato_EP71iMmmc0Q.webm" in service_worker
    assert "Content-Range" in service_worker


def test_epub_contains_the_complete_static_alignment() -> None:
    payload = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    with zipfile.ZipFile(EPUB_PATH) as archive:
        assert archive.testzip() is None
        assert archive.namelist()[0] == "mimetype"
        assert archive.read("mimetype") == b"application/epub+zip"

    book = epub.read_epub(str(EPUB_PATH))
    chapter_documents = sorted(
        (
            item
            for item in book.get_items_of_type(ITEM_DOCUMENT)
            if item.file_name.startswith("chapter-")
        ),
        key=lambda item: int(item.file_name.removeprefix("chapter-").removesuffix(".xhtml")),
    )
    assert len(chapter_documents) == 10

    rows = []
    for document in chapter_documents:
        soup = BeautifulSoup(document.get_content(), "lxml-xml")
        chapter_rows = soup.select("table.parallel-text tbody tr")
        assert all(row.select_one("td.italian p") for row in chapter_rows)
        assert all(row.select_one("td.english p") for row in chapter_rows)
        assert not soup.select("script, input, button, select")
        rows.extend(chapter_rows)

    assert len(rows) == payload["summary"]["alignment_units"]
    assert sum(bool(row.select_one(".supplement")) for row in rows) == 4
