from app.text_normalization import (
    canonical_authority_text,
    canonical_compact,
    canonical_equal,
    canonical_match_text,
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
    assert not is_safe_hungarian_entity_surface("Petoffi", "Petőfi")
    assert not is_safe_hungarian_entity_surface("Petőfi János", "Petőfi")
