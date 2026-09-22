from app.web_intent import is_factual_risk_request


def test_factual_relation_question_about_a_poem_is_not_treated_as_creative_generation():
    assert is_factual_risk_request(
        "Mikor írta Wrong Author a Silver Poem című verset?"
    ) is True


def test_factual_relation_question_about_a_story_is_not_treated_as_story_generation():
    assert is_factual_risk_request(
        "Who wrote Silver Story?"
    ) is True


def test_explicit_creative_generation_request_stays_non_factual():
    assert is_factual_risk_request(
        "Írj egy verset Wrong Author stílusában."
    ) is False


def test_explicit_rewrite_request_stays_non_factual():
    assert is_factual_risk_request(
        "Rewrite this story in a shorter style."
    ) is False
