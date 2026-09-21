import pytest

from app.context_guard import (
    ContextDriftError,
    extract_entity_anchors,
    guard_context_response,
    is_referential_followup,
    stale_subject_substitution,
)
from app.task_constraints import build_task_constraints


class RepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0, **kwargs):
        self.calls.append((model, messages, kwargs))
        return self.repaired


def test_extracts_named_and_model_like_entities():
    anchors = extract_entity_anchors("Tesla es Qwen3-Coder 30B osszehasonlitasa.")

    assert "Tesla" in anchors
    assert "Qwen3-Coder" in anchors
    assert "30B" in anchors


def test_referential_followup_is_not_treated_as_topic_switch():
    assert is_referential_followup("Es ennek mennyi az ara?") is True
    assert is_referential_followup("Melyik a Tesla aktualis ara?") is False


def test_detects_stale_subject_substitution():
    current = "Melyik a Tesla aktualis ara?"
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Melyik a Bitcoin aktualis ara?"},
        {"role": "assistant", "content": "A Bitcoin ara..."},
        {"role": "user", "content": current},
    ]

    stale = stale_subject_substitution(
        current,
        "A Bitcoin aktualis ara 60 000 USD.",
        messages,
        constraints=constraints,
    )

    assert "Bitcoin" in stale


def test_current_entity_presence_prevents_false_drift():
    current = "Hasonlitsd ossze a Tesla es Bitcoin teljesitmenyet."
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Korabban Qwen modellekrol beszeltunk."},
        {"role": "user", "content": current},
    ]

    stale = stale_subject_substitution(
        current,
        "A Tesla es a Bitcoin kulonbozo eszkozok; a Qwen itt nem relevans.",
        messages,
        constraints=constraints,
    )

    assert stale == ()


def test_referential_followup_allows_previous_entity_resolution():
    current = "Es ennek mennyi az ara?"
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Melyik Tesla modellt nezzuk?"},
        {"role": "assistant", "content": "A Model 3-at."},
        {"role": "user", "content": current},
    ]

    assert stale_subject_substitution(
        current,
        "A Tesla Model 3 ara...",
        messages,
        constraints=constraints,
    ) == ()


def test_guard_repairs_stale_subject_once():
    current = "Melyik a Tesla aktualis ara?"
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Melyik a Bitcoin aktualis ara?"},
        {"role": "user", "content": current},
    ]
    client = RepairClient("A Tesla aktualis ara 364 USD.")

    result = guard_context_response(
        client,
        "qwen-test",
        current,
        "A Bitcoin aktualis ara 60 000 USD.",
        messages,
        constraints=constraints,
    )

    assert result == "A Tesla aktualis ara 364 USD."
    assert len(client.calls) == 1


def test_guard_fails_closed_if_repair_still_uses_stale_subject():
    current = "Melyik a Tesla aktualis ara?"
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Melyik a Bitcoin aktualis ara?"},
        {"role": "user", "content": current},
    ]
    client = RepairClient("A Bitcoin aktualis ara 60 000 USD.")

    with pytest.raises(ContextDriftError):
        guard_context_response(
            client,
            "qwen-test",
            current,
            "A Bitcoin aktualis ara 60 000 USD.",
            messages,
            constraints=constraints,
        )
