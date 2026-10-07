from __future__ import annotations

import difflib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Sequence


TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class TimedToken:
    text: str
    normalized: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True)
class ReferenceToken:
    text: str
    normalized: str
    unit_index: int


@dataclass(frozen=True)
class TokenPair:
    reference_index: int
    asr_index: int
    similarity: float
    exact: bool


def normalize_tokens(text: str) -> tuple[str, ...]:
    """Return accent-insensitive lexical tokens for ebook/ASR comparison."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return tuple(TOKEN_PATTERN.findall(unaccented))


def timed_tokens(transcription: dict[str, Any]) -> tuple[TimedToken, ...]:
    """Flatten Whisper words and split contractions while retaining their time span."""
    output: list[TimedToken] = []
    for segment in transcription.get("segments", []):
        for word in segment.get("words", []):
            raw = str(word["word"])
            raw_parts = TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", raw))
            normalized_parts = normalize_tokens(raw)
            if not raw_parts or len(raw_parts) != len(normalized_parts):
                continue

            start = float(word["start"])
            end = float(word["end"])
            probability = float(word.get("probability", 0.0))
            weights = [max(len(part), 1) for part in raw_parts]
            total_weight = sum(weights)
            elapsed_weight = 0
            for raw_part, normalized, weight in zip(
                raw_parts, normalized_parts, weights, strict=True
            ):
                part_start = start + (end - start) * elapsed_weight / total_weight
                elapsed_weight += weight
                part_end = start + (end - start) * elapsed_weight / total_weight
                output.append(
                    TimedToken(
                        text=raw_part,
                        normalized=normalized,
                        start=part_start,
                        end=part_end,
                        probability=probability,
                    )
                )
    if not output:
        raise ValueError("The transcription contains no word timestamps")
    return tuple(output)


def reference_tokens(units: Sequence[dict[str, Any]]) -> tuple[ReferenceToken, ...]:
    output: list[ReferenceToken] = []
    for unit_index, unit in enumerate(units):
        text = str(unit["italian"])
        raw_parts = TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", text))
        normalized_parts = normalize_tokens(text)
        if len(raw_parts) != len(normalized_parts):
            raise ValueError(f"Could not tokenize {unit['id']}")
        output.extend(
            ReferenceToken(text=raw, normalized=normalized, unit_index=unit_index)
            for raw, normalized in zip(raw_parts, normalized_parts, strict=True)
        )
    return tuple(output)


def _token_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def _align_gap(
    reference: Sequence[ReferenceToken],
    asr: Sequence[TimedToken],
    reference_offset: int,
    asr_offset: int,
) -> list[TokenPair]:
    """Needleman-Wunsch alignment for a short gap between exact anchors."""
    n, m = len(reference), len(asr)
    if not n or not m:
        return []

    # SequenceMatcher normally leaves only short gaps. Guard against a malformed
    # transcript making quadratic dynamic programming unexpectedly expensive.
    if n * m > 250_000:
        return []

    gap_cost = 0.72
    costs = [[0.0] * (m + 1) for _ in range(n + 1)]
    moves = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        costs[i][0] = i * gap_cost
        moves[i][0] = 1
    for j in range(1, m + 1):
        costs[0][j] = j * gap_cost
        moves[0][j] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            similarity = _token_similarity(
                reference[i - 1].normalized, asr[j - 1].normalized
            )
            substitution = 0.42 + 0.58 * (1.0 - similarity)
            diagonal = costs[i - 1][j - 1] + substitution
            deletion = costs[i - 1][j] + gap_cost
            insertion = costs[i][j - 1] + gap_cost
            best = min(diagonal, deletion, insertion)
            costs[i][j] = best
            moves[i][j] = 0 if best == diagonal else (1 if best == deletion else 2)

    pairs: list[TokenPair] = []
    i, j = n, m
    while i or j:
        move = moves[i][j]
        if i and j and move == 0:
            similarity = _token_similarity(
                reference[i - 1].normalized, asr[j - 1].normalized
            )
            # A very weak substitution is less informative than interpolation
            # from the surrounding exact anchors.
            if similarity >= 0.34:
                pairs.append(
                    TokenPair(
                        reference_index=reference_offset + i - 1,
                        asr_index=asr_offset + j - 1,
                        similarity=similarity,
                        exact=similarity == 1.0,
                    )
                )
            i -= 1
            j -= 1
        elif i and (not j or move == 1):
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def align_tokens(
    reference: Sequence[ReferenceToken], asr: Sequence[TimedToken]
) -> tuple[TokenPair, ...]:
    """Monotonically align exact ebook tokens and nearby ASR substitutions."""
    reference_values = [token.normalized for token in reference]
    asr_values = [token.normalized for token in asr]
    matcher = difflib.SequenceMatcher(None, reference_values, asr_values, autojunk=True)
    blocks = matcher.get_matching_blocks()

    pairs: list[TokenPair] = []
    previous_reference = 0
    previous_asr = 0
    for block in blocks:
        pairs.extend(
            _align_gap(
                reference[previous_reference : block.a],
                asr[previous_asr : block.b],
                previous_reference,
                previous_asr,
            )
        )
        pairs.extend(
            TokenPair(
                reference_index=block.a + offset,
                asr_index=block.b + offset,
                similarity=1.0,
                exact=True,
            )
            for offset in range(block.size)
        )
        previous_reference = block.a + block.size
        previous_asr = block.b + block.size

    if any(
        left.reference_index >= right.reference_index
        or left.asr_index >= right.asr_index
        for left, right in zip(pairs, pairs[1:])
    ):
        raise AssertionError("Token alignment is not strictly monotonic")
    return tuple(pairs)


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _confidence(
    exact_ratio: float,
    aligned_ratio: float,
    mean_similarity: float,
    probability: float,
    start_anchored: bool,
    end_anchored: bool,
) -> str:
    if (
        exact_ratio >= 0.72
        and aligned_ratio >= 0.90
        and mean_similarity >= 0.92
        and probability >= 0.80
        and start_anchored
        and end_anchored
    ):
        return "high"
    if (
        aligned_ratio >= 0.50
        and mean_similarity >= 0.72
        and probability >= 0.55
        and (start_anchored or end_anchored)
    ):
        return "medium"
    return "low"


def unit_audio_ranges(
    units: Sequence[dict[str, Any]],
    reference: Sequence[ReferenceToken],
    asr: Sequence[TimedToken],
    pairs: Sequence[TokenPair],
) -> tuple[dict[str, Any], ...]:
    references_by_unit: list[list[int]] = [[] for _ in units]
    for reference_index, token in enumerate(reference):
        references_by_unit[token.unit_index].append(reference_index)

    pairs_by_reference = {pair.reference_index: pair for pair in pairs}
    ranges: list[dict[str, Any] | None] = []
    for indices in references_by_unit:
        unit_pairs = [pairs_by_reference[index] for index in indices if index in pairs_by_reference]
        if not unit_pairs:
            ranges.append(None)
            continue

        asr_indices = sorted({pair.asr_index for pair in unit_pairs})
        exact_count = sum(pair.exact for pair in unit_pairs)
        similarities = [pair.similarity for pair in unit_pairs]
        probabilities = [asr[index].probability for index in asr_indices]
        reference_count = len(indices)
        paired_reference_indices = {pair.reference_index for pair in unit_pairs}
        start_anchored = indices[0] in paired_reference_indices
        end_anchored = indices[-1] in paired_reference_indices
        leading_unaligned = next(
            (
                offset
                for offset, reference_index in enumerate(indices)
                if reference_index in paired_reference_indices
            ),
            reference_count,
        )
        trailing_unaligned = next(
            (
                offset
                for offset, reference_index in enumerate(reversed(indices))
                if reference_index in paired_reference_indices
            ),
            reference_count,
        )
        exact_ratio = exact_count / reference_count
        aligned_ratio = len(unit_pairs) / reference_count
        mean_similarity = sum(similarities) / len(similarities)
        mean_probability = sum(probabilities) / len(probabilities)
        start = asr[asr_indices[0]].start
        end = asr[asr_indices[-1]].end
        ranges.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "start_timestamp": format_timestamp(start),
                "end_timestamp": format_timestamp(end),
                "duration": round(max(end - start, 0.0), 3),
                "confidence": _confidence(
                    exact_ratio,
                    aligned_ratio,
                    mean_similarity,
                    mean_probability,
                    start_anchored,
                    end_anchored,
                ),
                "start_boundary": "aligned" if start_anchored else "inferred",
                "end_boundary": "aligned" if end_anchored else "inferred",
                "leading_unaligned_tokens": leading_unaligned,
                "trailing_unaligned_tokens": trailing_unaligned,
                "reference_tokens": reference_count,
                "aligned_tokens": len(unit_pairs),
                "exact_tokens": exact_count,
                "exact_token_ratio": round(exact_ratio, 4),
                "aligned_token_ratio": round(aligned_ratio, 4),
                "mean_token_similarity": round(mean_similarity, 4),
                "mean_asr_probability": round(mean_probability, 4),
            }
        )

    # Interpolate the rare unit with no usable lexical anchor. Weight by ebook
    # token count so adjacent unmatched units receive distinct monotonic ranges.
    index = 0
    while index < len(ranges):
        if ranges[index] is not None:
            index += 1
            continue
        run_start = index
        while index < len(ranges) and ranges[index] is None:
            index += 1
        run_end = index
        left = ranges[run_start - 1]["end"] if run_start else asr[0].start
        right = ranges[run_end]["start"] if run_end < len(ranges) else asr[-1].end
        counts = [len(references_by_unit[position]) for position in range(run_start, run_end)]
        total = max(sum(counts), 1)
        cursor = float(left)
        for position, count in zip(range(run_start, run_end), counts, strict=True):
            end = cursor + (float(right) - float(left)) * count / total
            ranges[position] = {
                "start": round(cursor, 3),
                "end": round(end, 3),
                "start_timestamp": format_timestamp(cursor),
                "end_timestamp": format_timestamp(end),
                "duration": round(max(end - cursor, 0.0), 3),
                "confidence": "low",
                "start_boundary": "interpolated",
                "end_boundary": "interpolated",
                "leading_unaligned_tokens": count,
                "trailing_unaligned_tokens": count,
                "reference_tokens": count,
                "aligned_tokens": 0,
                "exact_tokens": 0,
                "exact_token_ratio": 0.0,
                "aligned_token_ratio": 0.0,
                "mean_token_similarity": 0.0,
                "mean_asr_probability": 0.0,
                "interpolated": True,
            }
            cursor = end

    completed = tuple(item for item in ranges if item is not None)
    if len(completed) != len(units):
        raise AssertionError("A unit did not receive an audio range")

    # A split contraction can put two unit edges within the same Whisper word.
    # Divide only those overlaps; genuine silence remains outside both ranges.
    mutable = [dict(item) for item in completed]
    for previous, current in zip(mutable, mutable[1:]):
        if current["start"] < previous["end"]:
            boundary = (float(current["start"]) + float(previous["end"])) / 2
            previous["end"] = round(boundary, 3)
            previous["end_timestamp"] = format_timestamp(boundary)
            previous["duration"] = round(boundary - float(previous["start"]), 3)
            current["start"] = round(boundary, 3)
            current["start_timestamp"] = format_timestamp(boundary)
            current["duration"] = round(float(current["end"]) - boundary, 3)

    if any(
        float(item["start"]) > float(item["end"])
        or (position and float(item["start"]) < float(mutable[position - 1]["end"]))
        for position, item in enumerate(mutable)
    ):
        raise AssertionError("Audio ranges are not monotonic and non-overlapping")
    return tuple(mutable)


def duration_outlier_score(duration: float, token_count: int, seconds_per_token: float) -> float:
    """Symmetric log deviation from the book-wide narration rate."""
    expected = max(token_count * seconds_per_token, 0.001)
    return abs(math.log(max(duration, 0.001) / expected))
