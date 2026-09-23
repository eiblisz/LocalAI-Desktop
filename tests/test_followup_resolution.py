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


def test_concise_multiline_questions_are_not_misclassified_as_one_followup():
    prompt = "What is this?\nWhat is TCP?"

    result = resolve_contextual_followup(prompt, [])

    assert result.status == "direct"
    assert result.resolved_intent == prompt


def test_wrapped_short_followup_still_resolves_from_previous_context():
    result = resolve_contextual_followup(
        "How much is\nthis?",
        [
            {"role": "user", "content": "What is the price of the sample item?"},
            {"role": "assistant", "content": "The sample item costs 10 euros."},
        ],
    )

    assert result.status == "resolved"
    assert "sample item" in result.resolved_intent
    assert "10 euros" in result.resolved_intent
