"""Report extraction statistics and compare alternate source editions."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher

from viscount_aligner.sources import SOURCES, Chapter, extract_source


def source_text(chapters: tuple[Chapter, ...]) -> str:
    return "\n".join(paragraph for chapter in chapters for paragraph in chapter.paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect extracted EPUB story text.")
    parser.add_argument("sources", nargs="*", choices=sorted(SOURCES))
    args = parser.parse_args()
    keys = args.sources or list(SOURCES)

    extracted: dict[str, tuple[Chapter, ...]] = {}
    for key in keys:
        chapters = extract_source(SOURCES[key])
        extracted[key] = chapters
        print(f"\n{key}: {SOURCES[key].edition}")
        print("chapter  paragraphs  sentences  characters")
        for chapter in chapters:
            print(
                f"{chapter.number:>7}  {len(chapter.paragraphs):>10}  "
                f"{len(chapter.sentences):>9}  "
                f"{sum(len(p) for p in chapter.paragraphs):>10}"
            )
        print(
            f"total    {sum(len(c.paragraphs) for c in chapters):>10}  "
            f"{sum(len(c.sentences) for c in chapters):>9}  "
            f"{sum(len(p) for c in chapters for p in c.paragraphs):>10}"
        )
        print(f"first: {chapters[0].sentences[0].text}")
        print(f"last:  {chapters[-1].sentences[-1].text}")

    pairs = (("it_illustrated", "it_compact"), ("en_novella", "en_hmh"))
    for left, right in pairs:
        if left in extracted and right in extracted:
            ratio = SequenceMatcher(
                None, source_text(extracted[left]), source_text(extracted[right])
            ).ratio()
            print(f"\nnormalized character similarity {left} / {right}: {ratio:.6f}")


if __name__ == "__main__":
    main()
