from app.language_policy import (
    hungarian_output_quality_issues,
    repair_preserves_response_shape,
)
from app.request_trace import RequestTrace
from app.response_guard import guard_response, validate_response
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker


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
    assert result == draft.strip()
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
    repaired = draft.replace("loosely adatminta alapján", "adatmintákból")
    client = EditorialRepairClient(repaired)

    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
    )

    assert result == repaired.strip()
    assert len(client.calls) == 1
    assert repair_preserves_response_shape(draft, result)


def test_editorial_repair_rejects_shortened_long_answer():
    original = "\n\n".join(["Ez egy hosszú magyar bekezdés. " * 30] * 4)
    shortened = "Ez rövid lett."

    assert repair_preserves_response_shape(original, shortened) is False
