from app.direct_fact import (
    derive_premise_neutral_query,
    deterministic_hungarian_fact_fallback,
    targeted_fact_refinement_query,
    requested_fact_supported,
)


def test_marked_work_title_produces_entity_neutral_temporal_query():
    query, strategy = derive_premise_neutral_query(
        "Mikor írta Wrong Author a Silver Story című művet?",
        "temporal",
    )

    assert "Silver Story" in query
    assert "Wrong Author" not in query
    assert "composition" in query
    assert "publication" not in query
    assert strategy == "premise_neutral_title_relation"


def test_unmarked_hungarian_work_object_produces_premise_neutral_query():
    query, strategy = derive_premise_neutral_query(
        "Mikor írta Wrong Author a Silver Storyt?",
        "temporal",
    )

    assert query == "Silver Storyt composition writing date year"
    assert "Wrong Author" not in query
    assert strategy == "premise_neutral_title_relation"


def test_unmarked_hungarian_generic_object_is_not_misclassified_as_a_title():
    prompt = "Mikor írta Wrong Author a verset?"

    assert derive_premise_neutral_query(prompt, "temporal") == (
        prompt,
        "validated_original",
    )


def test_unmarked_free_form_request_falls_back_to_validated_original():
    prompt = "Mikor alakult a Sample Band?"

    assert derive_premise_neutral_query(prompt, "temporal") == (
        prompt,
        "validated_original",
    )


def test_short_named_identity_lookup_uses_the_subject_without_model_query_generation():
    assert derive_premise_neutral_query("Ki Sample Musician?", "identity") == (
        "Sample Musician",
        "identity_lookup_subject",
    )


def test_temporal_sufficiency_requires_a_date_like_literal():
    no_date = {"results": [{"snippet": "Silver Story was written by Correct Author."}]}
    with_date = {"results": [{"snippet": "Silver Story was published in 1912."}]}

    assert requested_fact_supported(no_date, "temporal") is False
    assert requested_fact_supported(with_date, "temporal") is True


def test_creation_request_rejects_an_unrelated_edition_year():
    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    edition_only = {
        "results": [{"snippet": "The 1922 edition is available in print."}],
    }
    composition_date = {
        "results": [{"snippet": "Silver Story was composed by Correct Author in 1912."}],
    }

    assert requested_fact_supported(edition_only, "temporal", prompt) is False
    assert requested_fact_supported(composition_date, "temporal", prompt) is True
    assert targeted_fact_refinement_query(prompt, "temporal") == (
        "Silver Story original composition year"
    )


def test_hungarian_fallback_only_repeats_a_supported_requested_literal():
    fallback = deterministic_hungarian_fact_fallback(
        "Relevant text: Sample Band formed in 1980.",
        "temporal",
    )

    assert fallback == "A rendelkezésre álló források alapján a kért időpont: 1980."
    assert deterministic_hungarian_fact_fallback("No date here", "temporal") == ""
