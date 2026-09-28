import json

import pytest

from app.response_guard import (
    ResponseValidationError,
    guard_response,
    normalize_user_visible_output,
    unexpected_script_issues,
    validate_response,
)
from app.ollama_client import ollama_failure_metadata
from app.task_constraints import build_task_constraints


def _passing_fluency_audit(messages):
    segments = json.loads(messages[1]["content"].split(
        "USER-VISIBLE RESPONSE SEGMENTS TO AUDIT:\n", 1
    )[1])
    return json.dumps({
        "judgments": [[item["id"], "pass"] for item in segments],
    })


class RepairClient:
    supports_hungarian_fluency_audit = True

    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        if "Hungarian fluency classifier" in messages[0]["content"]:
            return _passing_fluency_audit(messages)
        return self.repaired


def test_hungarian_response_rejects_accidental_hangul_leakage():
    prompt = "Válaszolj magyarul röviden."
    constraints = build_task_constraints(prompt)

    result = validate_response(
        prompt,
        "Ez egy magyar mondat, de közben 잘못 szó került bele.",
        constraints=constraints,
    )

    assert result.valid is False
    assert "unexpected_hangul" in result.issues
    assert result.evidence == ("잘못",)


def test_hungarian_response_rejects_accidental_cjk_leakage():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)

    result = validate_response(
        prompt,
        "Ez magyar szöveg 日本 véletlen beszúrással.",
        constraints=constraints,
    )

    assert "unexpected_cjk" in result.issues
    assert result.evidence == ("日本",)


def test_explicit_korean_request_allows_hangul_script():
    prompt = "Fordítsd le koreai nyelvre ezt: Jó reggelt."
    constraints = build_task_constraints(prompt)

    assert unexpected_script_issues(
        prompt,
        "좋은 아침입니다.",
        constraints=constraints,
    ) == ()


def test_quoted_unicode_name_and_source_metadata_are_tolerated():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)

    assert unexpected_script_issues(
        prompt,
        'A cikk a „서울경제” nevet használja.\nForrás: 서울경제',
        constraints=constraints,
    ) == ()


def test_guard_repairs_once_and_preserves_required_factual_literals_in_instruction():
    prompt = "Válaszolj magyarul: a modell ára 42 EUR, forrás https://example.test."
    constraints = build_task_constraints(prompt)
    client = RepairClient(
        "A modell ára 42 EUR."
    )

    result = guard_response(
        client,
        "qwen-test",
        prompt,
        "A modell ára 42 EUR 잘못. Forrás: https://example.test.",
        constraints=constraints,
    )

    assert result == "A modell ára 42 EUR. Forrás: https://example.test."
    assert len(client.calls) == 2


def test_guard_rejects_span_repair_that_changes_grounded_literals():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = RepairClient("Az ár 43 EUR.")

    with pytest.raises(ResponseValidationError, match="repair_integrity_failed") as exc:
        guard_response(
            client,
            "qwen-test",
            prompt,
            "The price is 42 EUR.",
            constraints=constraints,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_classification"] == "integrity_failed"
    assert metadata["ollama_call_phase"] == "repair_integrity_validation"

    assert len(client.calls) == 2
    system = client.calls[1][1][0]["content"]
    assert "Preserve every number" in system
    assert "strict JSON" in system


def test_guard_rejects_span_repair_that_changes_a_proper_name():
    prompt = "V\u00e1laszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = RepairClient("Kirk Hammett ismert zen\u00e9sz.")

    with pytest.raises(ResponseValidationError, match="repair_integrity_failed"):
        guard_response(
            client,
            "qwen-test",
            prompt,
            "James Hetfield loosely inspired ismert zen\u00e9sz.",
            constraints=constraints,
        )

    assert len(client.calls) == 2


def test_clean_response_keeps_outer_whitespace_unchanged():
    prompt = "V\u00e1laszolj magyarul."
    constraints = build_task_constraints(prompt)
    draft = "\n  Ez egy magyar v\u00e1lasz.  \n"
    client = RepairClient("this must not be used")

    assert guard_response(
        client,
        "qwen-test",
        prompt,
        draft,
        constraints=constraints,
    ) == draft
    assert len(client.calls) == 1


def test_guard_allows_locale_only_number_formatting_changes():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = RepairClient(
        "A növekedés 3,1% volt, az érték pedig 1 000 EUR."
    )

    result = guard_response(
        client,
        "qwen-test",
        prompt,
        "The growth was 3.1%, and the value was 1,000 EUR.",
        constraints=constraints,
    )

    assert result == "A növekedés 3,1% volt, az érték pedig 1 000 EUR."


def test_guard_fails_closed_after_one_bad_repair():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = RepairClient("Ez még mindig 잘못 válasz.")

    with pytest.raises(ResponseValidationError):
        guard_response(
            client,
            "qwen-test",
            prompt,
            "Első 잘못 válasz.",
            constraints=constraints,
        )

    assert len(client.calls) == 2


def test_normal_output_hygiene_removes_html_space_entities_from_prose():
    constraints = build_task_constraints("Írj magyar magyarázatot az internetről.")
    value = normalize_user_visible_output(
        "Első mondat.&amp;#x20;\n\nMásodik mondat.&#32;",
        constraints,
    )

    assert "&#x20;" not in value
    assert "&amp;#x20;" not in value
    assert "&#32;" not in value
    assert "Első mondat." in value
    assert "Második mondat." in value


def test_output_hygiene_preserves_entities_when_html_is_requested():
    constraints = build_task_constraints("Adj HTML példát.")
    value = normalize_user_visible_output("<p>A&#x20;B</p>", constraints)

    assert value == "<p>A&#x20;B</p>"


def test_output_hygiene_enforces_requested_paragraph_maximum_without_model_call():
    constraints = build_task_constraints(
        "Írj egy részletes, 6–8 bekezdéses magyar esszét az internetről."
    )
    draft = "\n\n".join(f"{index}. bekezdés tartalma." for index in range(1, 10))

    value = normalize_user_visible_output(draft, constraints)

    blocks = [item for item in value.split("\n\n") if item.strip()]
    assert len(blocks) == 8
    assert "8. bekezdés tartalma." in blocks[-1]
    assert "9. bekezdés tartalma." in blocks[-1]


def test_output_hygiene_handles_nested_amp_escaped_space_entity():
    constraints = build_task_constraints("Írj magyar magyarázatot.")
    value = normalize_user_visible_output(
        "Első.&amp;amp;#x20; Második.",
        constraints,
    )

    assert "x20" not in value
    assert "Első." in value
    assert "Második." in value


def test_output_hygiene_enforces_exact_paragraph_count_without_new_facts():
    constraints = build_task_constraints(
        "Írj egy 10 bekezdésből álló esszét a történelemről."
    )
    draft = "\n\n".join(
        f"{index}. bekezdés. Ez a meglévő tartalom második mondata."
        for index in range(1, 15)
    )

    value = normalize_user_visible_output(draft, constraints)

    blocks = [item for item in value.split("\n\n") if item.strip()]
    assert len(blocks) == 10
    assert "14. bekezdés." in blocks[-1]


def test_output_hygiene_preserves_paragraph_boundary_when_space_entity_ends_line():
    constraints = build_task_constraints(
        "Írj egy 2 bekezdésből álló esszét a történelemről."
    )
    draft = "Első bekezdés.&#x20;\nMásodik bekezdés.&amp;#x20;"

    value = normalize_user_visible_output(draft, constraints)

    assert "&#x20;" not in value
    assert "&amp;#x20;" not in value
    assert len([item for item in value.split("\n\n") if item.strip()]) == 2


def test_output_hygiene_can_split_existing_sentences_to_reach_exact_count():
    constraints = build_task_constraints(
        "Írj egy 3 bekezdésből álló esszét a történelemről."
    )
    draft = (
        "Első mondat. Második mondat. Harmadik mondat. "
        "Negyedik mondat. Ötödik mondat. Hatodik mondat."
    )

    value = normalize_user_visible_output(draft, constraints)

    blocks = [item for item in value.split("\n\n") if item.strip()]
    assert len(blocks) == 3
    assert "Első mondat." in value
    assert "Hatodik mondat." in value


def test_heading_does_not_count_toward_exact_paragraph_contract():
    constraints = build_task_constraints(
        "Írj egy 10 bekezdésből álló esszét a történelemről."
    )
    draft = "**Történelmi esszé**\n\n" + "\n\n".join(
        (
            f"{index}. bekezdés első mondata. "
            f"{index}. bekezdés második mondata."
        )
        for index in range(1, 10)
    )

    value = normalize_user_visible_output(draft, constraints)

    blocks = [item for item in value.split("\n\n") if item.strip()]
    assert blocks[0] == "**Történelmi esszé**"
    assert len(blocks[1:]) == 10


def test_exact_paragraph_contract_recognizes_single_newline_model_paragraphs():
    constraints = build_task_constraints(
        "Írj egy 10 bekezdésből álló esszét a történelemről."
    )
    draft = "**Történelmi esszé**\n" + "\n".join(
        (
            f"{index}. bekezdés első mondata. "
            f"{index}. bekezdés második mondata."
        )
        for index in range(1, 10)
    )

    value = normalize_user_visible_output(draft, constraints)
    blocks = [item for item in value.split("\n\n") if item.strip()]

    assert blocks[0] == "**Történelmi esszé**"
    assert len(blocks[1:]) == 10


def test_long_grounded_path_can_skip_optional_model_fluency_audit():
    prompt = "Írj magyarul egy hosszú történelmi esszét."
    constraints = build_task_constraints(prompt)
    client = RepairClient("this must not be used")

    result = guard_response(
        client,
        "qwen-test",
        prompt,
        "Ez egy teljesen magyar mondat.",
        constraints=constraints,
        run_model_fluency_audit=False,
    )

    assert result == "Ez egy teljesen magyar mondat."
    assert client.calls == []
