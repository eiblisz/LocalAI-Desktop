from app.text_normalization import (
    canonical_authority_text,
    canonical_compact,
    canonical_equal,
    canonical_contains_inflected,
    canonical_match_text,
    hungarian_token_matches,
    is_safe_hungarian_entity_surface,
)


def test_hungarian_accents_fold_without_dropping_base_letters_or_mutating_input():
    original = "János vitéz — írta?"

    assert canonical_match_text(original) == "janos vitez irta"
    assert canonical_compact(original) == "janosvitezirta"
    assert original == "János vitéz — írta?"


def test_accented_and_unaccented_forms_match_bidirectionally():
    assert canonical_equal("János", "Janos")
    assert canonical_equal("Pokolgép", "Pokolgep")
    assert canonical_authority_text("Gemma 4:26b") == "gemma 4 26b"


def test_safe_hungarian_case_suffixes_match_only_an_explicit_entity_base():
    assert is_safe_hungarian_entity_surface("Toldit", "Toldi")
    assert is_safe_hungarian_entity_surface("Pokolgépről", "Pokolgép")
    assert is_safe_hungarian_entity_surface("Petőfi Sándort", "Petőfi Sándor")
    assert is_safe_hungarian_entity_surface("Kisfaludy Társaságnál", "Kisfaludy Társaság")
    assert not is_safe_hungarian_entity_surface("Petoffi", "Petőfi")
    assert not is_safe_hungarian_entity_surface("Petőfi János", "Petőfi")


def test_shared_hungarian_morphology_profiles_cover_common_inflections():
    assert hungarian_token_matches(
        "bekezdésből",
        "bekezdes",
        profile="format",
    )
    assert hungarian_token_matches(
        "bekezdeses",
        "bekezdes",
        profile="format",
    )
    assert hungarian_token_matches(
        "zenekarnak",
        "zenekar",
        profile="entity",
    )
    assert hungarian_token_matches(
        "alakultak",
        "alakult",
        profile="semantic",
    )
    assert hungarian_token_matches(
        "keressetek",
        "keress",
        profile="command",
    )


def test_suffix_aware_phrase_matching_is_bounded_not_fuzzy():
    assert canonical_contains_inflected(
        "Mikor alakultak meg a csoportok?",
        "alakult",
        profile="semantic",
    )
    assert canonical_contains_inflected(
        "írj 10 bekezdésből álló esszét",
        "bekezdes",
        profile="format",
    )

    # Short function words must not grow into unrelated longer words.
    assert not canonical_contains_inflected(
        "a kiad fontos",
        "ki",
        profile="semantic",
    )
    # Unknown suffixes are not accepted merely because the token starts with
    # the same letters.
    assert not hungarian_token_matches(
        "bekezdesxyz",
        "bekezdes",
        profile="format",
    )
