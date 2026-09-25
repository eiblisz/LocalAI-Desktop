import json
import inspect

import pytest

from app.language_policy import (
    hungarian_output_quality_issues,
    repair_preserves_response_shape,
)
from app.request_trace import RequestTrace
from app.response_guard import LanguageRepairFailed, guard_response, validate_response
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker
from app.ollama_client import ollama_failure_metadata


class EditorialRepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return self.repaired


class SingleGenerationClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return self.response


def test_hungarian_quality_flags_generic_foreign_and_unicode_corruption():
    answer = (
        "A mesterséges intelligencia több módszert használ. "
        "A szöveg loosely inspirált példát ad, majd \ufffd hibás karaktert tartalmaz."
    )

    issues = hungarian_output_quality_issues(answer)

    assert "foreign_language_fragment" in issues
    assert "corrupted_unicode" in issues


def test_legitimate_technical_terms_are_not_treated_as_foreign_fragments():
    answer = (
        "Az LLM tokeneket dolgoz fel egy context window keretében. "
        "A training és inference GPU vagy Python eszközökkel is történhet."
    )

    assert "foreign_language_fragment" not in hungarian_output_quality_issues(answer)


def test_clean_long_hungarian_answer_passes_without_editorial_repair():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    constraints = build_task_constraints(prompt)
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    draft = "\n\n".join(paragraphs)
    client = EditorialRepairClient("this must not be used")

    validation = validate_response(prompt, draft, constraints=constraints)
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
    )

    assert validation.valid is True
    assert result == draft
    assert len(client.calls) == 0


def test_desktop_clean_long_answer_uses_only_primary_generation_call():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    answer = "\n\n".join(paragraphs)
    client = SingleGenerationClient(answer)
    trace = RequestTrace("desktop")
    worker = AdaptiveChatWorker(
        client,
        "gemma4:26b",
        [{"role": "user", "content": prompt}],
        prompt,
        constraints=build_task_constraints(prompt),
        trace=trace,
        output_budget=2048,
    )
    tokens = []
    errors = []
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)

    worker.run()

    snapshot = trace.snapshot()
    assert errors == []
    assert "".join(tokens) == answer.strip()
    assert len(client.calls) == 1
    assert snapshot["phases_ms"].get("primary_generation") is not None
    assert snapshot["phases_ms"].get("language_validation") is not None
    assert "language_repair" not in snapshot["phases_ms"]
    assert snapshot["metadata"]["language_validation_result"] == "pass"


def test_contaminated_long_hungarian_answer_gets_one_bounded_editorial_repair():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    constraints = build_task_constraints(prompt)
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    draft = "\n\n".join(paragraphs).replace(
        "adatmintákból", "loosely adatminta alapján", 1
    )
    class SpanRepairClient:
        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages, **kwargs):
            self.calls.append((model, messages, kwargs))
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({
                "repairs": [{
                    "id": item["id"],
                    "text": item["text"].replace(
                        "loosely adatminta alapján", "adatmintákból"
                    ),
                } for item in payload],
            })

    repaired = draft.replace("loosely adatminta alapján", "adatmintákból")
    client = SpanRepairClient()
    trace = RequestTrace("desktop")

    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
        trace=trace,
    )

    assert result == repaired
    assert len(client.calls) == 1
    assert repair_preserves_response_shape(draft, result)
    payload = json.loads(client.calls[0][1][1]["content"].split(
        "BOUNDED SPANS TO REPAIR:\n", 1
    )[1])
    assert len(payload) == 1
    assert "loosely" in payload[0]["text"]
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["language_repair_span_count"] == 1
    assert snapshot["metadata"]["language_repair_result"] == "completed"
    assert snapshot["metadata"]["repair_integrity_result"] == "pass"
    assert {"language_validation", "language_repair", "repair_integrity_validation"} <= set(
        snapshot["phases_ms"]
    )


def test_multiple_separated_contaminated_spans_preserve_untouched_text():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    untouched = "A harmadik bekezdés változatlan marad, benne az LLM és a GPU kifejezésekkel."
    draft = (
        "Az OpenAI modell ára 42 EUR, forrás: https://example.test. 잘못 mondat.\n\n"
        "A második bekezdés loosely kevert nyelvű maradt.\n\n"
        + untouched
    )

    class BatchSpanClient:
        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages, **kwargs):
            self.calls.append((model, messages, kwargs))
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({"repairs": [
                {
                    "id": item["id"],
                    "text": item["text"]
                    .replace("잘못", "hibás")
                    .replace("loosely", "véletlenül"),
                }
                for item in payload
            ]})

    client = BatchSpanClient()
    result = guard_response(
        client, "gemma4:26b", prompt, draft, constraints=constraints,
    )

    assert len(client.calls) == 1
    payload = json.loads(client.calls[0][1][1]["content"].split(
        "BOUNDED SPANS TO REPAIR:\n", 1
    )[1])
    assert len(payload) == 2
    assert untouched in result
    assert "OpenAI" in result
    assert "42 EUR" in result
    assert "https://example.test" in result
    assert "LLM" in result and "GPU" in result


def test_bounded_repair_that_keeps_contamination_is_language_repair_failure():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = EditorialRepairClient("Ez a mondat továbbra is 잘못 szöveget tartalmaz.")
    trace = RequestTrace("desktop")

    with pytest.raises(LanguageRepairFailed, match="language_repair_failed") as exc:
        guard_response(
            client,
            "gemma4:26b",
            prompt,
            "Ez a mondat 잘못 szöveget tartalmaz.",
            constraints=constraints,
            trace=trace,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_classification"] == "language_repair_failed"
    assert metadata["ollama_call_phase"] == "repair_integrity_validation"
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["language_repair_result"] == "completed"
    assert snapshot["metadata"]["repair_integrity_result"] == "failed"


def test_discord_and_desktop_use_the_shared_span_repair_guard():
    from app.discord_bot_bridge import DiscordBotBridge

    desktop_source = inspect.getsource(AdaptiveChatWorker.run)
    discord_source = inspect.getsource(DiscordBotBridge._answer_prompt)

    assert "guard_response(" in desktop_source
    assert "guard_response(" in discord_source


def test_editorial_repair_rejects_shortened_long_answer():
    original = "\n\n".join(["Ez egy hosszú magyar bekezdés. " * 30] * 4)
    shortened = "Ez rövid lett."

    assert repair_preserves_response_shape(original, shortened) is False
