from app.search_query_validation import validate_search_queries, validate_search_query


def test_punctuation_only_intent_cannot_produce_a_provider_query():
    result = validate_search_query("latest local model news", "?")

    assert not result.accepted


def test_query_generator_prose_and_unexpected_cjk_are_rejected():
    accepted, rejected = validate_search_queries(
        [
            "You should search for the user's request about Gemma.",
            "Gemma4 最新モデル release",
        ],
        "Melyik a legfrissebb Gemma4 modell?",
    )

    assert accepted == []
    assert "meta or query-writing prose" in rejected
    assert "unexpected script drift" in rejected


def test_hungarian_and_english_queries_for_same_intent_are_allowed():
    intent = "Mikor írta Arany János a Toldit?"

    assert validate_search_query("Arany János Toldi keletkezése", intent).accepted
    assert validate_search_query("Arany János Toldi date written", intent).accepted
