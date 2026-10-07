from __future__ import annotations

import json

from viscount_aligner.audio_alignment import (
    TimedToken,
    align_tokens,
    normalize_tokens,
    reference_tokens,
    unit_audio_ranges,
)
from viscount_aligner.paths import AUDIO_ALIGNMENT_PATH


def test_normalization_handles_italian_accents_and_elision() -> None:
    assert normalize_tokens("S’era già all’accampamento.") == (
        "s",
        "era",
        "gia",
        "all",
        "accampamento",
    )


def test_monotonic_alignment_tolerates_asr_variants_and_extra_words() -> None:
    units = [
        {"id": "one", "italian": "C’era una guerra contro i turchi."},
        {"id": "two", "italian": "Il visconte cavalcava in Boemia."},
    ]
    asr_words = (
        "c era una guerra contro i turchi dunque il visconte cavalcava in bohemia".split()
    )
    asr = tuple(
        TimedToken(
            text=word,
            normalized=word,
            start=index * 0.25,
            end=(index + 1) * 0.25,
            probability=0.95,
        )
        for index, word in enumerate(asr_words)
    )
    reference = reference_tokens(units)
    pairs = align_tokens(reference, asr)
    ranges = unit_audio_ranges(units, reference, asr, pairs)

    assert sum(pair.exact for pair in pairs) == len(reference) - 1
    assert len(pairs) == len(reference)
    assert ranges[0]["confidence"] == "high"
    assert ranges[1]["confidence"] == "high"
    assert ranges[0]["end"] <= ranges[1]["start"]


def test_audio_artifact_covers_every_bilingual_unit_monotonically() -> None:
    payload = json.loads(AUDIO_ALIGNMENT_PATH.read_text(encoding="utf-8"))
    units = payload["units"]

    assert len(units) == 1298
    assert payload["summary"]["alignment_units"] == len(units)
    # The narration includes the non-lexical "Zzt, zzt, zzt!", which Whisper
    # does not emit as words; its range is bounded by the neighboring anchors.
    assert payload["summary"]["interpolated_units"] <= 1
    assert all(unit["audio"]["start"] < unit["audio"]["end"] for unit in units)
    assert all(
        previous["audio"]["end"] <= current["audio"]["start"]
        for previous, current in zip(units, units[1:])
    )
    assert [unit["id"] for unit in units] == sorted(
        (unit["id"] for unit in units),
        key=lambda value: (int(value[1:3]), int(value.split("a")[-1])),
    )
