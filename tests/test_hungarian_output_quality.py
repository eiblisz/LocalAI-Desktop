from app.language_policy import (
    hungarian_output_quality_issues,
    repair_preserves_response_shape,
)
from app.response_guard import guard_response, validate_response
from app.task_constraints import build_task_constraints


class EditorialRepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        return self.repaired


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


def test_long_hungarian_answer_gets_one_bounded_editorial_repair():
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
    repaired = draft.replace("eredményt", "választ")
    client = EditorialRepairClient(repaired)

    validation = validate_response(prompt, draft, constraints=constraints)
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
    )

    assert "long_form_editorial_review" in validation.issues
    assert result == repaired.strip()
    assert len(client.calls) == 1
    assert repair_preserves_response_shape(draft, result)


def test_editorial_repair_rejects_shortened_long_answer():
    original = "\n\n".join(["Ez egy hosszú magyar bekezdés. " * 30] * 4)
    shortened = "Ez rövid lett."

    assert repair_preserves_response_shape(original, shortened) is False
