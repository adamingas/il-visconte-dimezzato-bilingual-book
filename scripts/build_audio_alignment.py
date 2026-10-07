"""Align the bilingual text groups with timestamped audiobook words."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from viscount_aligner.audio_alignment import (
    align_tokens,
    duration_outlier_score,
    format_timestamp,
    reference_tokens,
    timed_tokens,
    unit_audio_ranges,
)
from viscount_aligner.paths import (
    ALIGNMENT_PATH,
    AUDIO_ALIGNMENT_PATH,
    AUDIO_PATH,
    ROOT,
    TRANSCRIPTION_PATH,
)


DEFAULT_ALIGNMENT = ALIGNMENT_PATH
DEFAULT_TRANSCRIPTION = TRANSCRIPTION_PATH
DEFAULT_AUDIO = AUDIO_PATH
DEFAULT_OUTPUT = AUDIO_ALIGNMENT_PATH
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def _audio_metadata(path: Path) -> dict[str, Any]:
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = json.loads(process.stdout)
    stream = probe["streams"][0]
    container = probe["format"]
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    duration = float(container["duration"])
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": digest.hexdigest(),
        "duration": round(duration, 3),
        "duration_timestamp": format_timestamp(duration),
        "codec": stream["codec_name"],
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "size_bytes": int(container["size"]),
        "bit_rate": int(container["bit_rate"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map the existing bilingual groups onto Whisper word timestamps."
    )
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT)
    parser.add_argument("--transcription", type=Path, default=DEFAULT_TRANSCRIPTION)
    parser.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    bilingual = json.loads(args.alignment.read_text(encoding="utf-8"))
    transcription = json.loads(args.transcription.read_text(encoding="utf-8"))
    units = bilingual["units"]
    reference = reference_tokens(units)
    asr = timed_tokens(transcription)
    pairs = align_tokens(reference, asr)
    ranges = unit_audio_ranges(units, reference, asr, pairs)

    exact_tokens = sum(pair.exact for pair in pairs)
    aligned_tokens = len(pairs)
    mean_similarity = sum(pair.similarity for pair in pairs) / max(aligned_tokens, 1)
    probabilities = [token.probability for token in asr]
    first_start = float(ranges[0]["start"])
    last_end = float(ranges[-1]["end"])
    seconds_per_token = (last_end - first_start) / max(len(reference), 1)

    enriched_units = []
    for unit, audio_range in zip(units, ranges, strict=True):
        enriched = dict(unit)
        enriched["audio"] = dict(audio_range)
        enriched["audio"]["duration_outlier_score"] = round(
            duration_outlier_score(
                float(audio_range["duration"]),
                int(audio_range["reference_tokens"]),
                seconds_per_token,
            ),
            4,
        )
        enriched_units.append(enriched)

    payload = {
        "schema_version": 1,
        "audio": _audio_metadata(args.audio),
        "sources": bilingual["sources"],
        "method": {
            "name": "MLX Whisper acoustic anchors plus monotonic ebook token alignment",
            "asr_model": args.model,
            "language": "it",
            "word_timestamps": "Whisper cross-attention dynamic time warping",
            "text_alignment": "exact matching blocks plus local Needleman-Wunsch",
        },
        "summary": {
            "alignment_units": len(units),
            "reference_tokens": len(reference),
            "asr_tokens": len(asr),
            "aligned_tokens": aligned_tokens,
            "exact_tokens": exact_tokens,
            "aligned_token_ratio": round(aligned_tokens / len(reference), 6),
            "exact_token_ratio": round(exact_tokens / len(reference), 6),
            "mean_aligned_token_similarity": round(mean_similarity, 6),
            "mean_asr_probability": round(sum(probabilities) / len(probabilities), 6),
            "confidence": dict(Counter(item["confidence"] for item in ranges)),
            "interpolated_units": sum(bool(item.get("interpolated")) for item in ranges),
            "inferred_start_boundaries": sum(
                item["start_boundary"] != "aligned" for item in ranges
            ),
            "inferred_end_boundaries": sum(
                item["end_boundary"] != "aligned" for item in ranges
            ),
            "first_aligned_timestamp": ranges[0]["start_timestamp"],
            "last_aligned_timestamp": ranges[-1]["end_timestamp"],
        },
        "units": enriched_units,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
