"""Build the bilingual text alignment and render the HTML/EPUB readers."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from viscount_aligner.alignment import (
    align_book,
    apply_reviewed_merges,
    apply_supplements,
    embed_source,
    validate_coverage,
)
from viscount_aligner.paths import ALIGNMENT_PATH, EPUB_PATH, HTML_PATH, WORK_DIR
from viscount_aligner.render import render_epub, render_html
from viscount_aligner.site import sync_web_assets
from viscount_aligner.sources import SOURCES, extract_source


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bilingual sentence alignment.")
    parser.add_argument("--italian", choices=("it_illustrated", "it_compact"), default="it_illustrated")
    parser.add_argument("--english", choices=("en_novella", "en_hmh"), default="en_hmh")
    parser.add_argument("--output", type=Path, default=ALIGNMENT_PATH)
    parser.add_argument(
        "--html",
        type=Path,
        default=HTML_PATH,
    )
    parser.add_argument(
        "--epub",
        type=Path,
        default=EPUB_PATH,
    )
    args = parser.parse_args()

    italian = extract_source(SOURCES[args.italian])
    english = extract_source(SOURCES[args.english])
    cache_root = WORK_DIR / "embeddings"
    italian_embeddings = embed_source(italian, args.italian, cache_root)
    english_embeddings = embed_source(english, args.english, cache_root)
    units = align_book(italian, english, italian_embeddings, english_embeddings)
    units = apply_supplements(units)
    units = apply_reviewed_merges(units)
    validate_coverage(units, italian, english)

    payload = {
        "sources": {
            "italian": {"key": args.italian, "edition": SOURCES[args.italian].edition},
            "english": {"key": args.english, "edition": SOURCES[args.english].edition},
        },
        "summary": {
            "chapters": 10,
            "alignment_units": len(units),
            "italian_sentences": sum(len(chapter.sentences) for chapter in italian),
            "english_sentences": sum(len(chapter.sentences) for chapter in english),
            "confidence": dict(Counter(unit.confidence for unit in units)),
            "step_shapes": dict(
                Counter(f"{len(unit.italian)}:{len(unit.english)}" for unit in units)
            ),
        },
        "units": [
            {
                "id": unit.id,
                "chapter": unit.chapter,
                "italian_ids": [sentence.id for sentence in unit.italian],
                "english_ids": [sentence.id for sentence in unit.english],
                "italian": " ".join(sentence.text for sentence in unit.italian),
                "english": " ".join(sentence.text for sentence in unit.english),
                "similarity": round(unit.similarity, 6),
                "length_ratio": round(unit.length_ratio, 6),
                "confidence": unit.confidence,
            }
            for unit in units
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(units, SOURCES[args.italian], SOURCES[args.english], args.html)
    render_epub(units, SOURCES[args.italian], SOURCES[args.english], args.epub)
    sync_web_assets(args.html.parent)

    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.output}")
    print(f"Wrote {args.html}")
    print(f"Wrote {args.epub}")


if __name__ == "__main__":
    main()
