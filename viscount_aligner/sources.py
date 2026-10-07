from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from syntok import segmenter

from viscount_aligner.paths import SOURCES_DIR


@dataclass(frozen=True)
class SourceSpec:
    key: str
    path: Path
    language: str
    edition: str
    chapter_pattern: re.Pattern[str]
    chapter_offset: int = 0

    def chapter_number(self, file_name: str) -> int | None:
        match = self.chapter_pattern.search(file_name)
        if not match:
            return None
        chapter = int(match.group(1)) + self.chapter_offset
        return chapter if 1 <= chapter <= 10 else None


@dataclass(frozen=True)
class Sentence:
    id: str
    chapter: int
    paragraph: int
    position: int
    text: str


@dataclass(frozen=True)
class Chapter:
    number: int
    paragraphs: tuple[str, ...]
    sentences: tuple[Sentence, ...]


SOURCES = {
    "it_illustrated": SourceSpec(
        key="it_illustrated",
        path=SOURCES_DIR
        / "Il Visconte Dimezzato Italo Calvino, Emanuele Luzzati z-library.sk, 1lib.sk, z-lib.sk.epub",
        language="it",
        edition="Mondadori 2011 illustrated edition",
        chapter_pattern=re.compile(r"(?:^|/)\d+_chapter(\d+)\.xhtml$", re.IGNORECASE),
    ),
    "it_compact": SourceSpec(
        key="it_compact",
        path=SOURCES_DIR / "Il visconte dimezzato Italo Calvino z-library.sk, 1lib.sk, z-lib.sk.epub",
        language="it",
        edition="Mondadori 1993 compact edition",
        chapter_pattern=re.compile(r"(?:^|/)content(\d{4})\.xhtml$", re.IGNORECASE),
        chapter_offset=-4,
    ),
    "en_novella": SourceSpec(
        key="en_novella",
        path=SOURCES_DIR / "The Cloven Viscount - a novella Calvino Italo z-library.sk, 1lib.sk, z-lib.sk.epub",
        language="en",
        edition="Houghton Mifflin Harcourt novella edition",
        chapter_pattern=re.compile(r"(?:^|/)c(\d{2})\.xml$", re.IGNORECASE),
    ),
    "en_hmh": SourceSpec(
        key="en_hmh",
        path=SOURCES_DIR / "The Cloven Viscount Italo Calvino z-library.sk, 1lib.sk, z-lib.sk.epub",
        language="en",
        edition="Houghton Mifflin Harcourt EPUB 3 edition",
        chapter_pattern=re.compile(r"(?:^|/)c(\d{2})\.xhtml$", re.IGNORECASE),
    ),
}


def normalize_text(value: str) -> str:
    """Normalize encoding artifacts while preserving the published wording."""
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\u00ad", "").replace("\u00a0", " ")
    value = value.replace("\u201a", ",")
    return re.sub(r"\s+", " ", value).strip()


def _paragraphs(document: bytes) -> list[str]:
    soup = BeautifulSoup(document, "lxml-xml")
    paragraphs: list[str] = []
    for element in soup.find_all("p"):
        text = normalize_text(element.get_text(" ", strip=True))
        # The Italian editions append the original publication year after the novel.
        if text and not re.fullmatch(r"\(\d{4}\)", text):
            paragraphs.append(text)
    return paragraphs


def _sentences(paragraph: str) -> list[str]:
    return [
        normalize_text("".join(token.spacing + token.value for token in sentence))
        for syntok_paragraph in segmenter.analyze(paragraph)
        for sentence in syntok_paragraph
    ]


def extract_source(spec: SourceSpec) -> tuple[Chapter, ...]:
    if not spec.path.exists():
        raise FileNotFoundError(spec.path)

    book = epub.read_epub(str(spec.path), options={"ignore_ncx": False})
    documents: dict[int, list[str]] = {}
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        chapter_number = spec.chapter_number(item.file_name)
        if chapter_number is not None:
            documents[chapter_number] = _paragraphs(item.get_content())

    expected = set(range(1, 11))
    if set(documents) != expected:
        missing = sorted(expected - set(documents))
        raise ValueError(f"{spec.key}: expected chapters 1-10; missing {missing}")

    chapters: list[Chapter] = []
    for chapter_number in range(1, 11):
        sentences: list[Sentence] = []
        paragraphs = documents[chapter_number]
        for paragraph_number, paragraph in enumerate(paragraphs, start=1):
            parts = _sentences(paragraph)
            for sentence_number, text in enumerate(filter(None, parts), start=1):
                sentences.append(
                    Sentence(
                        id=(
                            f"{spec.language}-{chapter_number:02d}-"
                            f"p{paragraph_number:03d}-s{sentence_number:02d}"
                        ),
                        chapter=chapter_number,
                        paragraph=paragraph_number,
                        position=len(sentences) + 1,
                        text=text,
                    )
                )
        chapters.append(
            Chapter(
                number=chapter_number,
                paragraphs=tuple(paragraphs),
                sentences=tuple(sentences),
            )
        )
    return tuple(chapters)
