import pytest

from app.followup_resolution import resolve_contextual_followup


def test_punctuation_only_followup_without_context_needs_clarification():
    result = resolve_contextual_followup("?", [])

    assert result.needs_clarification
    assert not result.resolved_intent


def test_short_followup_is_resolved_from_the_previous_user_and_assistant_turn():
    result = resolve_contextual_followup(
        "miért?",
        [
            {"role": "user", "content": "Mikor írta Arany János a Toldit?"},
            {"role": "assistant", "content": "1846-ban írta."},
        ],
    )

    assert result.status == "resolved"
    assert "Arany János" in result.resolved_intent
    assert "1846" in result.resolved_intent
    assert result.resolved_intent != "miért?"


@pytest.mark.parametrize("followup", ["miert?", "es?", "mennyi?"])
def test_common_short_followups_still_resolve_from_previous_context(followup):
    result = resolve_contextual_followup(
        followup,
        [
            {"role": "user", "content": "Mikor alakult a Példa zenekar?"},
            {"role": "assistant", "content": "1980-ban alakult."},
        ],
    )

    assert result.status == "resolved"
    assert "Példa zenekar" in result.resolved_intent
    assert "1980" in result.resolved_intent
