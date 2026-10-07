from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from viscount_aligner.sources import Chapter, Sentence


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
STEPS = tuple((a, b) for a in range(1, 4) for b in range(1, 4)) + ((1, 0), (0, 1))

# Both supplied English EPUBs omit this short passage. These translations are
# kept explicit so source omissions cannot silently shift neighboring rows.
SUPPLEMENT_TRANSLATIONS = {
    "it-05-p010-s04": "—as he did whenever an improper subject was brought up.",
    "it-05-p010-s05": (
        "And, to change the subject, he would start telling stories about "
        "Captain Cook’s voyages."
    ),
    "it-05-p010-s06": (
        "Once I tried asking him how, in his opinion, my uncle could live so "
        "mutilated, but the Englishman could offer me nothing but that: "
        "“Oh, oh, oh! . . .”"
    ),
    "it-05-p010-s07": "Zzt, zzt, zzt!",
}


@dataclass(frozen=True)
class AlignmentUnit:
    id: str
    chapter: int
    italian: tuple[Sentence, ...]
    english: tuple[Sentence, ...]
    similarity: float
    length_ratio: float
    confidence: str


def _content_digest(chapters: tuple[Chapter, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(MODEL_NAME.encode())
    for chapter in chapters:
        for sentence in chapter.sentences:
            digest.update(sentence.id.encode())
            digest.update(sentence.text.encode())
    return digest.hexdigest()[:16]


def embed_source(
    chapters: tuple[Chapter, ...],
    source_key: str,
    cache_root: Path,
) -> tuple[np.ndarray, ...]:
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{source_key}-{_content_digest(chapters)}.npz"
    if cache_path.exists():
        archive = np.load(cache_path)
        return tuple(archive[f"chapter_{number}"] for number in range(1, 11))

    model = SentenceTransformer(
        MODEL_NAME,
        cache_folder=str(cache_root.parent / "huggingface"),
    )
    texts = [sentence.text for chapter in chapters for sentence in chapter.sentences]
    matrix = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    matrices: list[np.ndarray] = []
    offset = 0
    for chapter in chapters:
        length = len(chapter.sentences)
        matrices.append(np.asarray(matrix[offset : offset + length], dtype=np.float32))
        offset += length
    np.savez_compressed(
        cache_path,
        **{f"chapter_{i + 1}": value for i, value in enumerate(matrices)},
    )
    return tuple(matrices)


def _prefix_vectors(matrix: np.ndarray) -> np.ndarray:
    return np.vstack((np.zeros((1, matrix.shape[1]), dtype=np.float32), matrix.cumsum(0)))


def _group_vector(prefix: np.ndarray, start: int, end: int) -> np.ndarray:
    vector = prefix[end] - prefix[start]
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _prefix_lengths(sentences: tuple[Sentence, ...]) -> np.ndarray:
    values = np.fromiter((len(sentence.text) for sentence in sentences), dtype=np.float32)
    return np.concatenate((np.zeros(1, dtype=np.float32), values.cumsum()))


def _is_paragraph_end(sentences: tuple[Sentence, ...], end: int) -> bool:
    return end == len(sentences) or sentences[end - 1].paragraph != sentences[end].paragraph


def _score_candidate(
    italian: tuple[Sentence, ...],
    english: tuple[Sentence, ...],
    it_vectors: np.ndarray,
    en_vectors: np.ndarray,
    it_lengths: np.ndarray,
    en_lengths: np.ndarray,
    i: int,
    j: int,
    a: int,
    b: int,
    expected_ratio: float,
) -> tuple[float, float, float]:
    if not a or not b:
        # A gap is preferable to shifting the rest of a chapter, but still costs
        # more than retaining a weak genuine translation pair.
        return -0.22, -1.0, 0.0

    it_vector = _group_vector(it_vectors, i, i + a)
    en_vector = _group_vector(en_vectors, j, j + b)
    similarity = float(it_vector @ en_vector)

    it_chars = float(it_lengths[i + a] - it_lengths[i])
    en_chars = float(en_lengths[j + b] - en_lengths[j])
    length_ratio = en_chars / max(it_chars, 1.0)
    ratio_error = min(abs(math.log(max(length_ratio, 0.01) / expected_ratio)), 2.5)

    coverage_weight = (a + b) / 2
    score = coverage_weight * (similarity - 0.13 * ratio_error)

    it_boundary = _is_paragraph_end(italian, i + a)
    en_boundary = _is_paragraph_end(english, j + b)
    score += 0.045 if it_boundary == en_boundary else -0.025

    if a > 1 and b > 1:
        score -= 0.12 * min(a, b)
    if max(a, b) == 3:
        score -= 0.04
    return score, similarity, length_ratio


def _confidence(similarity: float, length_ratio: float, expected_ratio: float) -> str:
    ratio_error = abs(math.log(max(length_ratio, 0.01) / expected_ratio))
    if similarity >= 0.62 and ratio_error <= 0.75:
        return "high"
    if similarity >= 0.42 and ratio_error <= 1.25:
        return "medium"
    return "low"


def align_chapter(
    italian: Chapter,
    english: Chapter,
    italian_embeddings: np.ndarray,
    english_embeddings: np.ndarray,
) -> tuple[AlignmentUnit, ...]:
    it_sentences = italian.sentences
    en_sentences = english.sentences
    n, m = len(it_sentences), len(en_sentences)
    if italian_embeddings.shape[0] != n or english_embeddings.shape[0] != m:
        raise ValueError("Embedding count does not match sentence count")

    it_vectors = _prefix_vectors(italian_embeddings)
    en_vectors = _prefix_vectors(english_embeddings)
    it_lengths = _prefix_lengths(it_sentences)
    en_lengths = _prefix_lengths(en_sentences)
    expected_ratio = float(en_lengths[-1] / it_lengths[-1])

    scores = np.full((n + 1, m + 1), -np.inf, dtype=np.float32)
    back_a = np.zeros((n + 1, m + 1), dtype=np.int8)
    back_b = np.zeros((n + 1, m + 1), dtype=np.int8)
    scores[0, 0] = 0.0

    for i in range(n + 1):
        for j in range(m + 1):
            if not np.isfinite(scores[i, j]):
                continue
            for a, b in STEPS:
                if i + a > n or j + b > m:
                    continue
                if b and any(
                    sentence.id in SUPPLEMENT_TRANSLATIONS
                    for sentence in it_sentences[i : i + a]
                ):
                    continue
                if not b and it_sentences[i].id not in SUPPLEMENT_TRANSLATIONS:
                    continue
                if not a:
                    continue
                candidate, _, _ = _score_candidate(
                    it_sentences,
                    en_sentences,
                    it_vectors,
                    en_vectors,
                    it_lengths,
                    en_lengths,
                    i,
                    j,
                    a,
                    b,
                    expected_ratio,
                )
                total = float(scores[i, j]) + candidate
                if total > scores[i + a, j + b]:
                    scores[i + a, j + b] = total
                    back_a[i + a, j + b] = a
                    back_b[i + a, j + b] = b

    if not np.isfinite(scores[n, m]):
        raise RuntimeError(f"No complete alignment path for chapter {italian.number}")

    reverse_units: list[AlignmentUnit] = []
    i, j = n, m
    while i or j:
        a, b = int(back_a[i, j]), int(back_b[i, j])
        if not a and not b:
            raise RuntimeError(f"Broken alignment path at chapter {italian.number}: {i}, {j}")
        start_i, start_j = i - a, j - b
        _, similarity, length_ratio = _score_candidate(
            it_sentences,
            en_sentences,
            it_vectors,
            en_vectors,
            it_lengths,
            en_lengths,
            start_i,
            start_j,
            a,
            b,
            expected_ratio,
        )
        reverse_units.append(
            AlignmentUnit(
                id="",
                chapter=italian.number,
                italian=it_sentences[start_i:i],
                english=en_sentences[start_j:j],
                similarity=similarity,
                length_ratio=length_ratio,
                confidence=(
                    "gap"
                    if not a or not b
                    else _confidence(similarity, length_ratio, expected_ratio)
                ),
            )
        )
        i, j = start_i, start_j

    units: list[AlignmentUnit] = []
    for ordinal, unit in enumerate(reversed(reverse_units), start=1):
        units.append(
            AlignmentUnit(
                id=f"c{italian.number:02d}-a{ordinal:04d}",
                chapter=unit.chapter,
                italian=unit.italian,
                english=unit.english,
                similarity=unit.similarity,
                length_ratio=unit.length_ratio,
                confidence=unit.confidence,
            )
        )
    return tuple(units)


def align_book(
    italian: tuple[Chapter, ...],
    english: tuple[Chapter, ...],
    italian_embeddings: tuple[np.ndarray, ...],
    english_embeddings: tuple[np.ndarray, ...],
) -> tuple[AlignmentUnit, ...]:
    if len(italian) != 10 or len(english) != 10:
        raise ValueError("Expected ten chapters in both sources")
    units: list[AlignmentUnit] = []
    for index in range(10):
        units.extend(
            align_chapter(
                italian[index],
                english[index],
                italian_embeddings[index],
                english_embeddings[index],
            )
        )
    return tuple(units)


def apply_supplements(units: tuple[AlignmentUnit, ...]) -> tuple[AlignmentUnit, ...]:
    supplemented: list[AlignmentUnit] = []
    for unit in units:
        if unit.english:
            supplemented.append(unit)
            continue
        if len(unit.italian) != 1:
            raise AssertionError(f"Unexpected multi-sentence source gap in {unit.id}")
        italian = unit.italian[0]
        translation = SUPPLEMENT_TRANSLATIONS.get(italian.id)
        if translation is None:
            raise AssertionError(f"No reviewed supplement for {italian.id}")
        english = Sentence(
            id=f"supplement-{italian.id}",
            chapter=italian.chapter,
            paragraph=italian.paragraph,
            position=italian.position,
            text=translation,
        )
        supplemented.append(
            AlignmentUnit(
                id=unit.id,
                chapter=unit.chapter,
                italian=unit.italian,
                english=(english,),
                similarity=unit.similarity,
                length_ratio=len(translation) / max(len(italian.text), 1),
                confidence="supplemental",
            )
        )
    return tuple(supplemented)


def apply_reviewed_merges(units: tuple[AlignmentUnit, ...]) -> tuple[AlignmentUnit, ...]:
    """Merge the one reviewed dialogue boundary that crosses two DP units."""
    merged: list[AlignmentUnit] = []
    index = 0
    while index < len(units):
        unit = units[index]
        following = units[index + 1] if index + 1 < len(units) else None
        if (
            following is not None
            and unit.italian[-1].id == "it-01-p010-s03"
            and following.italian[0].id == "it-01-p010-s04"
        ):
            italian = unit.italian + following.italian
            english = unit.english + following.english
            merged.append(
                AlignmentUnit(
                    id=unit.id,
                    chapter=unit.chapter,
                    italian=italian,
                    english=english,
                    similarity=(unit.similarity + following.similarity) / 2,
                    length_ratio=(
                        sum(len(sentence.text) for sentence in english)
                        / sum(len(sentence.text) for sentence in italian)
                    ),
                    confidence="high",
                )
            )
            index += 2
            continue
        merged.append(unit)
        index += 1

    counters: dict[int, int] = {}
    renumbered: list[AlignmentUnit] = []
    for unit in merged:
        counters[unit.chapter] = counters.get(unit.chapter, 0) + 1
        renumbered.append(
            AlignmentUnit(
                id=f"c{unit.chapter:02d}-a{counters[unit.chapter]:04d}",
                chapter=unit.chapter,
                italian=unit.italian,
                english=unit.english,
                similarity=unit.similarity,
                length_ratio=unit.length_ratio,
                confidence=unit.confidence,
            )
        )
    return tuple(renumbered)


def validate_coverage(
    units: tuple[AlignmentUnit, ...],
    italian: tuple[Chapter, ...],
    english: tuple[Chapter, ...],
) -> None:
    expected_it = [sentence.id for chapter in italian for sentence in chapter.sentences]
    expected_en = [sentence.id for chapter in english for sentence in chapter.sentences]
    actual_it = [sentence.id for unit in units for sentence in unit.italian]
    actual_en = [
        sentence.id
        for unit in units
        for sentence in unit.english
        if not sentence.id.startswith("supplement-")
    ]
    if actual_it != expected_it:
        raise AssertionError("Italian coverage/order invariant failed")
    if actual_en != expected_en:
        raise AssertionError("English coverage/order invariant failed")
    if any(not unit.italian or not unit.english for unit in units):
        raise AssertionError("An alignment unit has an empty language side")
