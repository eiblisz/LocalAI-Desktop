import pytest

from app.direct_fact import (
    anchor_resolved_direct_fact_answer,
    answer_temporal_literals_supported_by_evidence,
    creation_answer_conflicts_with_evidence,
    derive_premise_neutral_query,
    direct_fact_title_surface,
    supported_creator_surfaces,
    deterministic_direct_fact_fallback,
    deterministic_hungarian_fact_fallback,
    resolve_debut_release_fact,
    targeted_fact_refinement_query,
    requested_fact_supported,
    unsupported_release_named_literals,
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


def test_lowercase_band_debut_release_query_is_premise_neutral():
    query, strategy = derive_premise_neutral_query(
        "Mikor adta ki az első nagylemezét a wasp együttes?",
        "temporal",
    )

    assert query == "wasp debut first album release date year"
    assert strategy == "premise_neutral_entity_release_relation"


def test_debut_release_evidence_binds_subject_relation_and_year_case_insensitively():
    prompt = "Mikor adta ki az első nagylemezét a wasp együttes?"
    evidence = {
        "results": [{
            "snippet": "W.A.S.P. released its self-titled debut album in 1984.",
        }],
    }

    assert requested_fact_supported(evidence, "temporal", prompt) is True
    assert answer_temporal_literals_supported_by_evidence(
        "Az első nagylemez 1984-ben jelent meg.",
        prompt,
        evidence,
    ) is True
    assert answer_temporal_literals_supported_by_evidence(
        "Az első nagylemez 1979-ben jelent meg.",
        prompt,
        evidence,
    ) is False


def test_debut_release_rejects_unrelated_year_even_when_result_mentions_band():
    prompt = "Mikor adta ki az első nagylemezét a wasp együttes?"
    evidence = {
        "results": [{
            "snippet": (
                "W.A.S.P. released its self-titled debut album in 1984. "
                "A separate retrospective mentions the year 1979."
            ),
        }],
    }

    assert answer_temporal_literals_supported_by_evidence(
        "A debütáló album 1979-ben jelent meg.",
        prompt,
        evidence,
    ) is False


def test_debut_release_accepts_short_paraphrase_between_first_and_album():
    prompt = "Mikor adta ki az első nagylemezét a sampleband együttes?"
    repaired_answer = {
        "results": [{
            "snippet": (
                "A sampleband első, saját nevét viselő albuma "
                "1984-ben jelent meg."
            ),
        }],
    }

    assert requested_fact_supported(
        repaired_answer,
        "temporal",
        prompt,
    ) is True



@pytest.mark.parametrize(
    ("prompt", "expected_subject"),
    [
        ("Mikor adta ki az első nagylemezét a sampleband együttes?", "sampleband"),
        ("Mikor adta ki az első nagylemezét a SAMPLEBAND együttes?", "SAMPLEBAND"),
        ("Mikor jelent meg a sampleband együttes első albuma?", "sampleband"),
        ("Mikor adta ki a debütáló albumát a sampleband zenekar?", "sampleband"),
        ("When did sampleband release its first album?", "sampleband"),
    ],
)
def test_debut_release_variants_build_entity_bound_neutral_queries(prompt, expected_subject):
    query, strategy = derive_premise_neutral_query(prompt, "temporal")

    assert query == f"{expected_subject} debut first album release date year"
    assert strategy == "premise_neutral_entity_release_relation"


@pytest.mark.parametrize(
    "prompt",
    [
        "Mikor adta ki az első nagylemezét a sampleband együttes?",
        "Mikor adta ki az első nagylemezét a SAMPLEBAND együttes?",
        "Mikor jelent meg a sampleband együttes első albuma?",
        "When did sampleband release its first album?",
    ],
)
def test_debut_release_evidence_acceptance_is_case_and_wording_invariant(prompt):
    evidence = {
        "results": [{
            "snippet": "S.A.M.P.L.E.B.A.N.D. released its debut album in 1984.",
        }],
    }

    assert requested_fact_supported(evidence, "temporal", prompt) is True
    assert answer_temporal_literals_supported_by_evidence(
        "A debütáló album 1984-ben jelent meg.",
        prompt,
        evidence,
    ) is True
    assert answer_temporal_literals_supported_by_evidence(
        "A debütáló album 1979-ben jelent meg.",
        prompt,
        evidence,
    ) is False



def test_first_album_title_question_without_entity_type_builds_bound_query():
    prompt = "mi volt a sampleband elso albumanak a cime?"
    query, strategy = derive_premise_neutral_query(prompt, "selection")

    assert query == "sampleband debut first album discography"
    assert strategy == "premise_neutral_entity_release_relation"


def test_debut_fact_subject_binding_tolerates_high_similarity_spelling_error():
    prompt = "melyik nagylemez volt az elso a samplband zenekarnak?"
    evidence = {
        "results": [{
            "title": "Sampleband discography",
            "snippet": "Sampleband released its self-titled debut album in 1984.",
        }],
    }

    fact = resolve_debut_release_fact(evidence, prompt)

    assert fact["subject"] == "Sampleband"
    assert fact["title"] == "Sampleband"


def test_debut_fact_subject_binding_rejects_low_similarity_short_neighbor():
    prompt = "melyik nagylemez volt az elso a samplband zenekarnak?"
    evidence = {
        "results": [{
            "title": "Samp discography",
            "snippet": "Samp released its self-titled debut album in 1984.",
        }],
    }

    assert resolve_debut_release_fact(evidence, prompt) == {}


def test_first_album_selection_builds_premise_neutral_entity_query():
    prompt = "Melyik nagylemez volt az első a sampleband zenekarnak?"
    query, strategy = derive_premise_neutral_query(prompt, "selection")

    assert query == "sampleband debut first album discography"
    assert strategy == "premise_neutral_entity_release_relation"


def test_first_album_selection_requires_subject_bound_debut_evidence():
    prompt = "Melyik nagylemez volt az első a sampleband zenekarnak?"
    good = {
        "results": [{
            "snippet": "S.A.M.P.L.E.B.A.N.D. released its self-titled debut album in 1984.",
        }],
    }
    unrelated = {
        "results": [{
            "snippet": "Another Band released its debut album in 1984.",
        }],
    }

    assert requested_fact_supported(good, "selection", prompt) is True
    assert requested_fact_supported(unrelated, "selection", prompt) is False


def test_release_extra_quoted_title_requires_same_result_subject_binding():
    prompt = "Melyik nagylemez volt az első a sampleband zenekarnak?"
    evidence = {
        "results": [
            {
                "title": "Sample Band debut album",
                "snippet": (
                    "S.A.M.P.L.E.B.A.N.D. released its self-titled debut album "
                    "in 1984. It includes the track \"Real Track\"."
                ),
            },
            {
                "title": "Other Band songs",
                "snippet": 'Other Band recorded "Wrong Track".',
            },
        ],
    }

    assert unsupported_release_named_literals(
        'A debütáló albumon szerepel a "Real Track".',
        prompt,
        evidence,
    ) == ()
    assert unsupported_release_named_literals(
        'A debütáló albumon szerepel a "Wrong Track".',
        prompt,
        evidence,
    ) == ("Wrong Track",)
    assert unsupported_release_named_literals(
        "A debütáló album egyik dala a Wrong Track.",
        prompt,
        evidence,
    ) == ("Wrong Track",)


def test_host_resolves_self_titled_debut_selection_from_bound_evidence():
    prompt = "melyik nagylemez volt az elso a wasp zenekarnak?"
    evidence = {
        "results": [{
            "title": "W.A.S.P. discography",
            "snippet": (
                "W.A.S.P. is the debut studio album by American heavy metal "
                "band W.A.S.P., released in 1984."
            ),
        }],
    }

    fact = resolve_debut_release_fact(evidence, prompt)

    assert fact["title"] == "W.A.S.P."
    assert fact["subject"] == "W.A.S.P."
    assert fact["year"] == "1984"

    answer = deterministic_direct_fact_fallback(
        evidence,
        prompt,
        "selection",
        language="hu",
    )
    assert "első nagylemeze" in answer
    assert "W.A.S.P" in answer
    assert "1984" in answer


def test_host_direct_fact_fallback_fails_closed_on_conflicting_debut_titles():
    prompt = "Melyik nagylemez volt az első a sampleband zenekarnak?"
    evidence = {
        "results": [
            {
                "title": "Alpha",
                "snippet": "Alpha is the debut studio album by Sampleband.",
            },
            {
                "title": "Beta",
                "snippet": "Beta is the debut studio album by Sampleband.",
            },
        ],
    }

    assert resolve_debut_release_fact(evidence, prompt) == {}
    assert deterministic_direct_fact_fallback(
        evidence,
        prompt,
        "selection",
        language="hu",
    ) == ""


def test_host_resolves_first_album_from_artist_overview_without_using_band_page_title():
    prompt = "melyik nagylemez volt az elso a wasp zenekarnak?"
    evidence = {
        "results": [{
            "title": "W.A.S.P. (band)",
            "snippet": (
                "W.A.S.P. is an American heavy metal band. Their first two "
                "full-length studio albums, W.A.S.P. (1984) and "
                "The Last Command (1985), were certified gold."
            ),
        }],
    }

    fact = resolve_debut_release_fact(evidence, prompt)

    assert fact["title"] == "W.A.S.P."
    assert "(band)" not in fact["title"]
    assert fact["year"] == "1984"


def test_host_anchor_replaces_wrong_core_sentence_and_preserves_supporting_context():
    fact = {
        "subject": "W\\.A.S.P.",
        "title": "W\\.A.S.P.",
        "year": "1984",
        "relation": "release",
    }
    draft = (
        "The Last Command volt az első nagylemez. "
        "A zenekar az 1980-as években vált ismertté."
    )

    anchored = anchor_resolved_direct_fact_answer(
        draft,
        fact,
        "selection",
        language="hu",
    )

    assert anchored.startswith(
        "A W.A.S.P. első nagylemeze a W.A.S.P. című album volt."
    )
    assert "1984" in anchored
    assert "The Last Command" not in anchored
    assert "A zenekar az 1980-as években vált ismertté." in anchored
    assert "\\." not in anchored
