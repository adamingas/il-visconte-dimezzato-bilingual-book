from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from diskcache import Cache

from viscount_aligner.sources import Sentence


_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "add_literal_translations.py"
_SPEC = importlib.util.spec_from_file_location("add_literal_translations", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
literal = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = literal
_SPEC.loader.exec_module(literal)


def _sentence(
    sentence_id: str,
    text: str,
    *,
    chapter: int = 1,
    position: int = 1,
) -> Sentence:
    return Sentence(
        id=sentence_id,
        chapter=chapter,
        paragraph=1,
        position=position,
        text=text,
    )


def test_jobs_supply_only_the_previous_two_sentences_within_the_chapter() -> None:
    sentences = (
        _sentence("s1", "Prima.", position=1),
        _sentence("s2", "Seconda.", position=2),
        _sentence("s3", "Terza.", position=3),
        _sentence("s4", "Quarta.", position=4),
        _sentence("s5", "Nuovo capitolo.", chapter=2, position=1),
    )

    jobs = literal._translation_jobs(sentences)

    assert jobs[0].context == ()
    assert jobs[1].context == ("Prima.",)
    assert jobs[2].context == ("Prima.", "Seconda.")
    assert jobs[3].context == ("Seconda.", "Terza.")
    assert jobs[4].context == ()


def test_prompt_marks_context_and_target_without_exposing_sentence_id() -> None:
    job = literal.TranslationJob(
        sentence=_sentence("secret-id", "Traduci soltanto questo."),
        context=("Non tradurre questo.", "Neanche questo."),
    )

    prompt = literal._user_prompt(job)

    assert "secret-id" not in prompt
    assert prompt.count("<context_do_not_translate>") == 1
    assert prompt.count("<target_translate_only>") == 1
    assert "1. Non tradurre questo." in prompt
    assert "2. Neanche questo." in prompt
    assert re.search(
        r"<target_translate_only>\nTraduci soltanto questo\.\n</target_translate_only>",
        prompt,
    )


def test_cache_key_is_sha256_of_the_exact_complete_request() -> None:
    job = literal.TranslationJob(
        sentence=_sentence("s1", "Bersaglio."),
        context=("Contesto.",),
    )
    payload = literal._request_payload(job, "model-a")
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert literal._cache_key(payload) == (
        "literal-translation:"
        + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    )

    changed_context = literal.TranslationJob(
        sentence=job.sentence,
        context=("Contesto cambiato.",),
    )
    assert literal._cache_key(
        literal._request_payload(changed_context, "model-a")
    ) != literal._cache_key(payload)
    assert literal._cache_key(
        literal._request_payload(job, "model-b")
    ) != literal._cache_key(payload)
    assert payload["response_format"] == literal.TRANSLATION_RESPONSE_FORMAT


def test_prompt_does_not_describe_the_structured_output_envelope() -> None:
    assert "english_translation" not in literal.SYSTEM_PROMPT
    assert "JSON" not in literal.SYSTEM_PROMPT


def test_diskcache_resume_requires_an_identical_request(tmp_path) -> None:
    job = literal.TranslationJob(
        sentence=_sentence("s1", "Bersaglio."),
        context=("Contesto.",),
    )
    changed = literal.TranslationJob(
        sentence=job.sentence,
        context=("Altro contesto.",),
    )
    cache = Cache(str(tmp_path / "cache"))
    try:
        request = literal._request_payload(job, "model-a")
        cache.set(literal._cache_key(request), "Target.")

        assert literal._load_cached((job,), cache, "model-a") == {
            "s1": "Target."
        }
        assert literal._load_cached((changed,), cache, "model-a") == {}
    finally:
        cache.close()


class _FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def create(self, **request):
        self.requests.append(request)
        user_prompt = request["messages"][1]["content"]
        target = re.search(
            r"<target_translate_only>\n(.*?)\n</target_translate_only>",
            user_prompt,
            re.DOTALL,
        ).group(1)
        content = json.dumps({"english_translation": f"English: {target}"})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_successful_requests_are_written_immediately_and_resume(tmp_path) -> None:
    jobs = literal._translation_jobs(
        (
            _sentence("s1", "Prima.", position=1),
            _sentence("s2", "Seconda.", position=2),
        )
    )
    client = _FakeClient()
    completed: dict[str, str] = {}
    cache = Cache(str(tmp_path / "cache"))
    try:
        asyncio.run(
            literal._run_jobs(
                jobs,
                completed,
                client,
                "model-a",
                cache,
                concurrency=2,
                max_attempts=1,
            )
        )

        assert completed == {"s1": "English: Prima.", "s2": "English: Seconda."}
        assert len(client.completions.requests) == 2
        assert literal._load_cached(jobs, cache, "model-a") == completed
    finally:
        cache.close()


def test_preflight_selects_ten_distinct_cases_from_the_input() -> None:
    payload = json.loads(literal.DEFAULT_INPUT.read_text(encoding="utf-8"))
    jobs = literal._translation_jobs(literal._source_sentences(payload))
    preflight = literal._preflight_jobs(payload, jobs, 10)

    assert len(preflight) == 10
    assert len({job.sentence.id for job in preflight}) == 10
    first_three_sentence_unit = next(
        unit for unit in payload["units"] if len(unit["italian_ids"]) >= 3
    )
    assert [job.sentence.id for job in preflight[:3]] == first_three_sentence_unit[
        "italian_ids"
    ][:3]


def test_preflight_accepts_caller_selected_sentence_ids() -> None:
    payload = json.loads(literal.DEFAULT_INPUT.read_text(encoding="utf-8"))
    jobs = literal._translation_jobs(literal._source_sentences(payload))
    requested = (jobs[7].sentence.id, jobs[101].sentence.id)

    selected = literal._preflight_jobs(payload, jobs, 10, requested)

    assert tuple(job.sentence.id for job in selected) == requested
