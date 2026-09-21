import pytest

from app.response_guard import (
    ResponseValidationError,
    guard_response,
    unexpected_script_issues,
    validate_response,
)
from app.task_constraints import build_task_constraints


class RepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
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


def test_hungarian_response_rejects_accidental_cjk_leakage():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)

    issues = unexpected_script_issues(
        prompt,
        "Ez magyar szöveg 日本 véletlen beszúrással.",
        constraints=constraints,
    )

    assert "unexpected_cjk" in issues


def test_explicit_korean_request_allows_hangul_script():
    prompt = "Fordítsd le koreai nyelvre ezt: Jó reggelt."
    constraints = build_task_constraints(prompt)

    assert unexpected_script_issues(
        prompt,
        "좋은 아침입니다.",
        constraints=constraints,
    ) == ()


def test_guard_repairs_once_and_preserves_required_factual_literals_in_instruction():
    prompt = "Válaszolj magyarul: a modell ára 42 EUR, forrás https://example.test."
    constraints = build_task_constraints(prompt)
    client = RepairClient(
        "A modell ára 42 EUR, forrás: https://example.test."
    )

    result = guard_response(
        client,
        "qwen-test",
        prompt,
        "A modell ára 42 EUR 잘못. Forrás: https://example.test.",
        constraints=constraints,
    )

    assert result == "A modell ára 42 EUR, forrás: https://example.test."
    assert len(client.calls) == 1
    system = client.calls[0][1][0]["content"]
    assert "Preserve every URL, number" in system
    assert "Do not add new facts" in system


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

    assert len(client.calls) == 1
