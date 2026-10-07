"""Generate literal translations and merge them into the reader artifacts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

from diskcache import Cache
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from viscount_aligner.alignment import AlignmentUnit
from viscount_aligner.paths import ALIGNMENT_PATH, HTML_PATH, ROOT, TRANSLATION_CACHE_DIR
from viscount_aligner.render import render_html
from viscount_aligner.site import sync_web_assets
from viscount_aligner.sources import SOURCES, Sentence, extract_source


DEFAULT_INPUT = ALIGNMENT_PATH
DEFAULT_CACHE = TRANSLATION_CACHE_DIR
DEFAULT_HTML = HTML_PATH
CONTEXT_SENTENCE_COUNT = 2
PROMPT_VERSION = 10

SYSTEM_PROMPT = """Translate exactly one target Italian sentence into literal English.

The user message contains optional Italian context and one target sentence. The context is supplied only to resolve meaning. Never translate, repeat, summarize, or import words from the context. Return only the translation of the text inside <target_translate_only>.

Translate the target as strictly word for word as English permits. Keep its clause order, grammatical structure, tense, person, number, articles, pronouns, negation, repetition, punctuation, and register. Translate every target word or expression into English; only genuine proper names may remain unchanged. Never copy the Italian target unchanged and never leave an Italian word or phrase untranslated. Rare Italian common nouns must also be translated rather than copied; for example, ghiri means dormice. Do not paraphrase, clarify, improve, summarize, omit, or add information. Awkward English is correct when it reflects the Italian structure."""

class TranslationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    english_translation: str


TRANSLATION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "literal_translation",
        "strict": True,
        "schema": TranslationOutput.model_json_schema(),
    },
}


@dataclass(frozen=True)
class TranslationJob:
    sentence: Sentence
    context: tuple[str, ...]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _source_sentences(payload: dict) -> tuple[Sentence, ...]:
    source = SOURCES[payload["sources"]["italian"]["key"]]
    return tuple(
        sentence
        for chapter in extract_source(source)
        for sentence in chapter.sentences
    )


def _translation_jobs(sentences: tuple[Sentence, ...]) -> tuple[TranslationJob, ...]:
    jobs: list[TranslationJob] = []
    previous: list[str] = []
    previous_chapter: int | None = None
    for sentence in sentences:
        if sentence.chapter != previous_chapter:
            previous = []
            previous_chapter = sentence.chapter
        jobs.append(
            TranslationJob(
                sentence=sentence,
                context=tuple(previous[-CONTEXT_SENTENCE_COUNT:]),
            )
        )
        previous.append(sentence.text)
    return tuple(jobs)


def _user_prompt(job: TranslationJob) -> str:
    if job.context:
        context = "\n".join(
            f"{index}. {text}" for index, text in enumerate(job.context, start=1)
        )
    else:
        context = "(none)"
    return (
        "<context_do_not_translate>\n"
        f"{context}\n"
        "</context_do_not_translate>\n\n"
        "<target_translate_only>\n"
        f"{job.sentence.text}\n"
        "</target_translate_only>"
    )


def _request_payload(job: TranslationJob, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(job)},
        ],
        "temperature": 0,
        "seed": 0,
        "reasoning_effort": "low",
        # GPT-OSS counts hidden reasoning against this limit. A small cap that is
        # adequate for Gemma can therefore truncate the structured JSON before
        # the visible translation is complete. The server stops as soon as the
        # schema is satisfied, so this safety margin does not force extra output.
        "max_tokens": 1024,
    }
    payload["response_format"] = TRANSLATION_RESPONSE_FORMAT
    return payload


def _cache_key(request_payload: dict) -> str:
    """Hash the exact inference request; any prompt or context change misses cache."""
    serialized = json.dumps(
        request_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"literal-translation:{digest}"


def estimate_inference_size(jobs: tuple[TranslationJob, ...]) -> dict[str, int]:
    request_characters = sum(
        len(
            json.dumps(
                _request_payload(job, "<runtime-model>"),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        for job in jobs
    )
    source_characters = sum(len(job.sentence.text) for job in jobs)
    return {
        "sentences": len(jobs),
        "request_characters": request_characters,
        "source_characters": source_characters,
    }


def _clean_translation(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    if "<|channel>final" in value:
        value = value.split("<|channel>final", 1)[1]
    value = re.split(r"<channel\|>|<turn\|>|<\|turn>", value, maxsplit=1)[0].strip()
    if not value or "<|channel>thought" in value:
        raise ValueError("model returned no clean final response")
    return value


def _parse_response(content: str) -> str:
    cleaned = _clean_translation(content)
    payload = TranslationOutput.model_validate_json(cleaned)
    english = payload.english_translation.strip()
    if not english:
        raise ValueError("model returned an empty translation")
    return english


def _retry_delay(error: Exception, attempt: int) -> float:
    headers = getattr(getattr(error, "response", None), "headers", {})
    retry_after = headers.get("retry-after") if headers else None
    if retry_after:
        try:
            return max(0.25, float(retry_after))
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)(ms|s|m)", str(error), re.IGNORECASE)
    if match:
        value = float(match.group(1))
        scale = {"ms": 0.001, "s": 1.0, "m": 60.0}[match.group(2).lower()]
        return max(0.25, value * scale)
    return min(8.0, 2**attempt)


def _is_retryable(error: Exception) -> bool:
    from openai import APIConnectionError, APITimeoutError

    status = getattr(error, "status_code", None)
    return status in {408, 409, 429, 500, 502, 503, 504} or isinstance(
        error, (APIConnectionError, APITimeoutError)
    )


async def _request_translation(
    job: TranslationJob,
    client,
    model: str,
    semaphore: asyncio.Semaphore,
    max_attempts: int,
) -> tuple[str, dict]:
    request_payload = _request_payload(job, model)
    for attempt in range(max_attempts):
        try:
            async with semaphore:
                result = await client.chat.completions.create(**request_payload)
            return _parse_response(result.choices[0].message.content or ""), request_payload
        except Exception as error:
            if attempt == max_attempts - 1 or not _is_retryable(error):
                raise RuntimeError(
                    f"translation failed for {job.sentence.id} after {attempt + 1} attempt(s)"
                ) from error
            await asyncio.sleep(
                _retry_delay(error, attempt) + random.uniform(0.05, 0.2)
            )
    raise AssertionError("unreachable")


def _load_cached(
    jobs: tuple[TranslationJob, ...],
    cache: Cache,
    model: str,
) -> dict[str, str]:
    completed: dict[str, str] = {}
    for job in jobs:
        request_payload = _request_payload(job, model)
        cached = cache.get(_cache_key(request_payload))
        if isinstance(cached, str) and cached.strip():
            completed[job.sentence.id] = cached.strip()
    return completed


async def _run_jobs(
    jobs: tuple[TranslationJob, ...],
    completed: dict[str, str],
    client,
    model: str,
    cache: Cache,
    concurrency: int,
    max_attempts: int,
) -> None:
    pending = [job for job in jobs if job.sentence.id not in completed]
    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    translated_this_run = 0

    async def translate_one(job: TranslationJob) -> None:
        nonlocal translated_this_run
        english, request_payload = await _request_translation(
            job,
            client,
            model,
            semaphore,
            max_attempts,
        )
        # diskcache is the durable checkpoint. A successful result is persisted
        # before it is counted as complete.
        await asyncio.to_thread(cache.set, _cache_key(request_payload), english)
        completed[job.sentence.id] = english
        async with progress_lock:
            translated_this_run += 1
            if translated_this_run % 25 == 0 or translated_this_run == len(pending):
                print(
                    f"Translated {len(completed)}/{len(jobs)} sentences",
                    flush=True,
                )

    await asyncio.gather(*(translate_one(job) for job in pending))


def _preflight_jobs(
    payload: dict,
    jobs: tuple[TranslationJob, ...],
    count: int,
    requested_ids: tuple[str, ...] = (),
) -> tuple[TranslationJob, ...]:
    by_id = {job.sentence.id: job for job in jobs}
    if requested_ids:
        missing = [sentence_id for sentence_id in requested_ids if sentence_id not in by_id]
        if missing:
            raise RuntimeError(f"preflight sentence is missing from source: {missing[0]}")
        return tuple(by_id[sentence_id] for sentence_id in requested_ids)

    selected: list[TranslationJob] = []
    selected_ids: set[str] = set()

    def add(job: TranslationJob) -> None:
        if job.sentence.id not in selected_ids and len(selected) < count:
            selected.append(job)
            selected_ids.add(job.sentence.id)

    # Start with consecutive members of one multi-sentence alignment unit. This
    # directly tests that context does not leak across target boundaries.
    for unit in payload["units"]:
        if len(unit["italian_ids"]) >= 3:
            for sentence_id in unit["italian_ids"][:3]:
                add(by_id[sentence_id])
            break

    # Exercise both extremes, then distribute the remaining cases across the book.
    add(min(jobs, key=lambda job: len(job.sentence.text)))
    add(max(jobs, key=lambda job: len(job.sentence.text)))
    if count > len(selected):
        slots = count - len(selected)
        for slot in range(slots):
            index = round(slot * (len(jobs) - 1) / max(1, slots - 1))
            add(jobs[index])
    for job in jobs:
        add(job)
        if len(selected) == count:
            break
    return tuple(selected)


async def _run_preflight(
    payload: dict,
    jobs: tuple[TranslationJob, ...],
    client,
    model: str,
    max_attempts: int,
    count: int,
    requested_ids: tuple[str, ...],
) -> None:
    semaphore = asyncio.Semaphore(1)
    results = []
    preflight_jobs = _preflight_jobs(payload, jobs, count, requested_ids)
    for index, job in enumerate(preflight_jobs, start=1):
        english, _ = await _request_translation(
            job,
            client,
            model,
            semaphore,
            max_attempts,
        )
        results.append(
            {
                "case": index,
                "italian_id": job.sentence.id,
                "context_do_not_translate": list(job.context),
                "target_translate_only": job.sentence.text,
                "english_translation": english,
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False, indent=2), flush=True)
    print(f"Preflight completed: {len(results)}/{len(preflight_jobs)} responses")


def _alignment_units(payload: dict) -> tuple[AlignmentUnit, ...]:
    italian = {
        sentence.id: sentence
        for chapter in extract_source(SOURCES[payload["sources"]["italian"]["key"]])
        for sentence in chapter.sentences
    }
    english = {
        sentence.id: sentence
        for chapter in extract_source(SOURCES[payload["sources"]["english"]["key"]])
        for sentence in chapter.sentences
    }
    units: list[AlignmentUnit] = []
    for item in payload["units"]:
        english_sentences = []
        for sentence_id in item["english_ids"]:
            sentence = english.get(sentence_id)
            if sentence is None:
                sentence = Sentence(
                    id=sentence_id,
                    chapter=item["chapter"],
                    paragraph=0,
                    position=0,
                    text=item["english"],
                )
            english_sentences.append(sentence)
        units.append(
            AlignmentUnit(
                id=item["id"],
                chapter=item["chapter"],
                italian=tuple(italian[sentence_id] for sentence_id in item["italian_ids"]),
                english=tuple(english_sentences),
                similarity=item["similarity"],
                length_ratio=item["length_ratio"],
                confidence=item["confidence"],
            )
        )
    return tuple(units)


def _enrich(payload: dict, translations: dict[str, str], model: str) -> None:
    sentences = {sentence.id: sentence for sentence in _source_sentences(payload)}
    for unit in payload["units"]:
        unit["literal_english_sentences"] = [
            {
                "italian_id": sentence_id,
                "italian": sentences[sentence_id].text,
                "english": translations[sentence_id],
            }
            for sentence_id in unit["italian_ids"]
        ]
        unit["literal_english"] = " ".join(
            translations[sentence_id] for sentence_id in unit["italian_ids"]
        )
    payload["literal_translation"] = {
        "provider": "openai-compatible",
        "model": model,
        "method": (
            "one target Italian sentence per request; previous two source sentences "
            "supplied as context-only; one-field Pydantic structured output; no IDs "
            "or published English supplied; temperature 0"
        ),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "context_sentences": CONTEXT_SENTENCE_COUNT,
        "sentence_count": len(sentences),
    }


def _validate_completed(jobs: tuple[TranslationJob, ...], completed: dict[str, str]) -> None:
    expected_ids = [job.sentence.id for job in jobs]
    if len(expected_ids) != len(set(expected_ids)):
        raise RuntimeError("Italian source contains duplicate sentence IDs")
    missing = [sentence_id for sentence_id in expected_ids if sentence_id not in completed]
    unknown = [sentence_id for sentence_id in completed if sentence_id not in set(expected_ids)]
    empty = [sentence_id for sentence_id, text in completed.items() if not text.strip()]
    if missing or unknown or empty:
        raise RuntimeError(
            f"invalid completed translations: missing={len(missing)}, "
            f"unknown={len(unknown)}, empty={len(empty)}"
        )


async def _run(args, jobs: tuple[TranslationJob, ...], payload: dict) -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=args.api_key,
        base_url=args.base_url,
        timeout=args.timeout,
        max_retries=0,
    )
    try:
        models = await client.models.list()
        available_models = [item.id for item in models.data]
        print(
            json.dumps(
                {
                    "endpoint": args.base_url,
                    "requested_model": args.model,
                    "available_models": available_models,
                },
                indent=2,
            ),
            flush=True,
        )
        if args.model not in available_models:
            raise RuntimeError(
                f"requested model {args.model!r} is not served by {args.base_url}"
            )
        if args.command == "preflight":
            await _run_preflight(
                payload,
                jobs,
                client,
                args.model,
                args.max_attempts,
                args.count,
                tuple(args.sentence_id),
            )
            return

        cache = Cache(str(args.cache))
        try:
            completed = _load_cached(jobs, cache, args.model)
            print(
                f"Loaded {len(completed)} translations from diskcache",
                flush=True,
            )
            await _run_jobs(
                jobs,
                completed,
                client,
                args.model,
                cache,
                args.concurrency,
                args.max_attempts,
            )
        finally:
            cache.close()

        _validate_completed(jobs, completed)
        _enrich(payload, completed, args.model)
        _write_json(args.output, payload)

        units = _alignment_units(payload)
        render_html(
            units,
            SOURCES[payload["sources"]["italian"]["key"]],
            SOURCES[payload["sources"]["english"]["key"]],
            args.html,
            literal_translations=completed,
        )
        sync_web_assets(args.html.parent)
        print(f"Wrote {args.output}")
        print(f"Wrote {args.html}")
    finally:
        await client.close()


def main() -> None:
    # Local endpoint configuration may be stored in the ignored .env file.
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description=(
            "Generate literal translations through an OpenAI-compatible MLX or "
            "vLLM endpoint, enrich alignment JSON, and rebuild the HTML reader."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_input_argument(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)

    def add_endpoint_arguments(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--base-url",
            default=os.environ.get("LITERAL_BASE_URL"),
            help="OpenAI-compatible /v1 endpoint (or set LITERAL_BASE_URL).",
        )
        command_parser.add_argument(
            "--model",
            default=os.environ.get("LITERAL_MODEL"),
            help="Model name served by the endpoint (or set LITERAL_MODEL).",
        )
        command_parser.add_argument(
            "--api-key",
            default=os.environ.get("LITERAL_API_KEY", "local-endpoint"),
            help="Bearer token for the endpoint.",
        )
        command_parser.add_argument("--timeout", type=float, default=180)
        command_parser.add_argument("--max-attempts", type=int, default=5)

    preflight_parser = commands.add_parser(
        "preflight", help="Translate representative targets without using the cache."
    )
    add_input_argument(preflight_parser)
    add_endpoint_arguments(preflight_parser)
    preflight_parser.add_argument("--count", type=int, default=10)
    preflight_parser.add_argument(
        "--sentence-id",
        action="append",
        default=[],
        help="Translate this sentence ID; repeat to choose exact preflight cases.",
    )

    translate_parser = commands.add_parser(
        "translate", help="Translate the complete corpus and rebuild outputs."
    )
    add_input_argument(translate_parser)
    add_endpoint_arguments(translate_parser)
    translate_parser.add_argument("--output", type=Path, default=DEFAULT_INPUT)
    translate_parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    translate_parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    translate_parser.add_argument("--concurrency", type=int, default=50)

    estimate_parser = commands.add_parser(
        "estimate", help="Print request size without contacting an endpoint."
    )
    add_input_argument(estimate_parser)
    commands.add_parser("show-prompt", help="Print the translation system prompt.")
    args = parser.parse_args()

    if args.command == "show-prompt":
        print(SYSTEM_PROMPT)
        return
    if args.command == "estimate":
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        jobs = _translation_jobs(_source_sentences(payload))
        print(json.dumps(estimate_inference_size(jobs), indent=2))
        return
    if not args.base_url:
        parser.error("--base-url or LITERAL_BASE_URL is required")
    if not args.model:
        parser.error("--model or LITERAL_MODEL is required")
    if args.command == "translate" and args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.command == "preflight" and args.count < 1:
        parser.error("--count must be at least 1")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    jobs = _translation_jobs(_source_sentences(payload))
    asyncio.run(_run(args, jobs, payload))


if __name__ == "__main__":
    main()
