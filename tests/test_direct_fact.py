from app.direct_fact import (
    creation_answer_conflicts_with_evidence,
    derive_premise_neutral_query,
    direct_fact_title_surface,
    supported_creator_surfaces,
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
    assert "keletkezés" in query
    assert "publication" not in query
    assert strategy == "premise_neutral_title_relation"


def test_unmarked_hungarian_work_object_produces_premise_neutral_query():
    query, strategy = derive_premise_neutral_query(
        "Mikor írta Wrong Author a Silver Storyt?",
        "temporal",
    )

    assert query == "Silver Story szerző keletkezés megírás éve"
    assert "Wrong Author" not in query
    assert strategy == "premise_neutral_title_relation"


def test_direct_fact_title_surface_returns_prompt_work_lemma():
    assert direct_fact_title_surface(
        "Mikor írta Wrong Author a Toldit?"
    ) == "Toldi"


def test_unmarked_hungarian_object_search_surface_strips_accusative_only_for_search():
    query, strategy = derive_premise_neutral_query(
        "Mikor írta Wrong Author a Toldit?",
        "temporal",
    )

    assert query == "Toldi szerző keletkezés megírás éve"
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
        "Silver Story szerző eredeti keletkezés éve"
    )


def test_creation_request_rejects_publication_year_even_with_authorship_in_same_result():
    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    mixed_publication = {
        "results": [{
            "snippet": (
                "Silver Story was first published in 1922. "
                "Correct Author wrote it for the competition."
            ),
        }],
    }

    assert requested_fact_supported(
        mixed_publication,
        "temporal",
        prompt,
    ) is False


def test_creation_request_rejects_hungarian_release_verb_as_writing_date():
    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    release_only = {
        "results": [{
            "snippet": (
                "A Silver Story szerzője Correct Author, "
                "aki 1912-ben adta ki a művet."
            ),
        }],
    }

    assert requested_fact_supported(
        release_only,
        "temporal",
        prompt,
    ) is False


def test_creation_request_accepts_creation_year_when_publication_year_is_also_present():
    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    mixed_dates = {
        "results": [{
            "snippet": (
                "Correct Author wrote Silver Story in 1912. "
                "It was first published in 1922."
            ),
        }],
    }

    assert requested_fact_supported(
        mixed_dates,
        "temporal",
        prompt,
    ) is True


def test_supported_creator_surface_does_not_absorb_following_lowercase_words():
    evidence = {
        "results": [{
            "snippet": "Silver Story was written by Correct Author in 1912.",
        }],
    }

    assert supported_creator_surfaces(evidence) == ("Correct Author",)


def test_creation_answer_rejects_false_creator_even_when_noisy_evidence_mentions_both():
    prompt = "Mikor írta Wrong Author a Silver Storyt?"
    evidence = {
        "results": [
            {"snippet": "Wrong Author wrote about the Silver Story question."},
            {"snippet": "Silver Story was written by Correct Author in 1912."},
        ],
    }

    assert creation_answer_conflicts_with_evidence(
        "Wrong Author (Correct Author) a Silver Storyt 1912-ben írta.",
        prompt,
        evidence,
    ) is True


def test_creation_answer_requires_verification_when_creator_evidence_is_missing():
    prompt = "Mikor írta Wrong Author a Silver Storyt?"
    evidence = {"results": [{"snippet": "Silver Story keletkezési éve 1912."}]}

    assert creation_answer_conflicts_with_evidence(
        "Wrong Author 1912-ben írta a Silver Storyt.",
        prompt,
        evidence,
    ) is True


def test_creation_answer_accepts_affirmed_creator_when_evidence_uniquely_supports_it():
    prompt = "Mikor írta Correct Author a Silver Storyt?"
    evidence = {
        "results": [{
            "snippet": "Silver Story was written by Correct Author in 1912.",
        }],
    }

    assert creation_answer_conflicts_with_evidence(
        "Correct Author 1912-ben írta a Silver Storyt.",
        prompt,
        evidence,
    ) is False


def test_creation_answer_rejects_affirmed_false_creator_premise():
    prompt = "Mikor írta Wrong Author a Silver Storyt?"
    evidence = {
        "results": [{
            "snippet": "Silver Story was written by Correct Author in 1912.",
        }],
    }

    assert creation_answer_conflicts_with_evidence(
        "Wrong Author (Correct Author) a Silver Storyt 1912-ben írta.",
        prompt,
        evidence,
    ) is True
    assert creation_answer_conflicts_with_evidence(
        "Wrong Author nem írta a Silver Storyt; Correct Author írta 1912-ben.",
        prompt,
        evidence,
    ) is False


def test_hungarian_fallback_only_repeats_a_supported_requested_literal():
    fallback = deterministic_hungarian_fact_fallback(
        "Relevant text: Sample Band formed in 1980.",
        "temporal",
    )

    assert fallback == "A rendelkezésre álló források alapján a kért időpont: 1980."
    assert deterministic_hungarian_fact_fallback("No date here", "temporal") == ""
