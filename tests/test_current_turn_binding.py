import pytest

from app.current_turn_binding import (
    CurrentTurnBindingError,
    grounded_answer_mentions_current_entity,
    guard_current_turn_binding,
    prompt_entity_anchors,
)


class RepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = 0

    def chat_once(self, model, messages, timeout=600.0, **kwargs):
        self.calls += 1
        return self.repaired


def test_prompt_entity_anchors_are_accent_insensitive():
    anchors = prompt_entity_anchors("Mikor írta Arany Janos a Jans vitezt?")

    assert "arany" in anchors
    assert "janos" in anchors


def test_grounded_answer_keeps_current_entity_binding():
    assert grounded_answer_mentions_current_entity(
        "Mikor írta Arany Janos a Jans vitezt?",
        "Arany János nem írta ezt a művet; a szerző Petőfi Sándor.",
    ) is True


def test_adjacent_topic_without_current_entity_is_rejected_for_repair():
    client = RepairClient(
        "Arany János nem írta a János vitézt; a mű Petőfi Sándor alkotása."
    )

    result = guard_current_turn_binding(
        client,
        "qwen-test",
        "Mikor írta Arany Janos a Jans vitezt?",
        "A történet főhőse Kukorica Jancsi, és több kalandon megy keresztül.",
        "AUTHORIZED EVIDENCE: A János vitéz Petőfi Sándor műve.",
    )

    assert "Arany" in result
    assert client.calls == 1


def test_guard_fails_closed_if_repair_still_drifts():
    client = RepairClient(
        "Kukorica Jancsi kalandjai a történet központi elemei."
    )

    with pytest.raises(CurrentTurnBindingError):
        guard_current_turn_binding(
            client,
            "qwen-test",
            "Mikor írta Arany Janos a Jans vitezt?",
            "Kukorica Jancsi kalandjairól szól.",
            "AUTHORIZED EVIDENCE: A János vitéz Petőfi Sándor műve.",
        )

    assert client.calls == 1


def test_prompts_without_entity_anchors_are_not_forced():
    assert guard_current_turn_binding(
        RepairClient("unused"),
        "qwen-test",
        "Miért fontos ellenőrizni a forrásokat?",
        "A forrásellenőrzés csökkenti a tévedések kockázatát.",
        "evidence",
    ).startswith("A forrásellenőrzés")
