from app.language_policy import (
    detect_user_language,
    effective_response_language,
    response_language_instruction,
    response_language_matches,
    response_language_repair_instruction,
)


def test_detects_short_hungarian_identity_question():
    assert detect_user_language("ki Zsofia?") == "hu"


def test_detects_hungarian_memory_request_without_accents():
    assert detect_user_language("jegyezd meg hogy Zsofia Kristof baratnoje") == "hu"


def test_detects_hungarian_from_accents():
    assert detect_user_language("Zsófia Kristóf barátnője") == "hu"


def test_detects_english_question():
    assert detect_user_language("Who is Zsofia?") == "en"


def test_hungarian_instruction_forces_hungarian_response():
    instruction = response_language_instruction("ki Zsofia?")
    assert "Kizárólag magyarul" in instruction
    assert "Hungarian only" in instruction
    assert "Do not switch to English" in instruction


def test_unknown_language_still_forbids_unrequested_switching():
    instruction = response_language_instruction("Zsofia?")
    assert "Hungarian only" in instruction


def test_ambiguous_turn_uses_hungarian_as_the_canonical_default():
    assert effective_response_language("Zsofia?") == "hu"
    assert response_language_matches("Zsofia?", "A válasz magyarul érkezett.")
    assert not response_language_matches(
        "Zsofia?",
        "The answer remains entirely in English with several words.",
    )


def test_german_umlaut_alone_is_not_misclassified_as_hungarian():
    assert detect_user_language("Wie viel kostet das für mich?") != "hu"


def test_detects_german_request():
    assert detect_user_language("Wie viel kostet diese SSD und wo kann ich sie kaufen?") == "de"


def test_hungarian_response_language_rejects_clearly_german_answer():
    from app.language_policy import response_language_matches

    assert not response_language_matches(
        "Keress nekem 4 TB-os SSD-t",
        "Die Suche zeigt viele Angebote und Preise. Hier sind die besten Produkte.",
    )


def test_hungarian_response_language_accepts_hungarian_answer():
    from app.language_policy import response_language_matches

    assert response_language_matches(
        "Keress nekem 4 TB-os SSD-t",
        "Ellenőrzött termékszintű találatok. Csak olyan árat mutatok, amely igazolt.",
    )




def test_detects_general_hungarian_instruction_prompt():
    assert (
        detect_user_language(
            "Válaszolj magyarul egy rövid összefoglalóban az AI Desktop munkanapjáról."
        )
        == "hu"
    )


def test_detects_hungarian_command_without_special_oo_uu_markers():
    assert detect_user_language("Irj magyarul reszletes elemzest.") == "hu"



def test_common_hungarian_factual_question_is_detected_as_hungarian():
    assert detect_user_language(
        "Mikor írta Arany Janos a Janos vitez cimu verset?"
    ) == "hu"



def test_short_hungarian_band_fact_answer_is_accepted():
    assert response_language_matches(
        "mikor alakult a pokolgep?",
        "A Pokolgép 1980-ban alakult Budapesten, és a magyar heavy metal egyik "
        "meghatározó zenekara lett.",
    )


def test_english_answer_with_hungarian_proper_name_is_rejected():
    assert not response_language_matches(
        "mikor alakult a pokolgep?",
        "The band Pokolgép was formed in 1980 and is one of the best known "
        "Hungarian heavy metal groups.",
    )


def test_hungarian_repair_instruction_is_itself_hungarian_and_strict():
    instruction = response_language_repair_instruction(
        "mikor alakult a pokolgep?"
    )
    assert "kizárólag magyar" in instruction.casefold()
    assert "személynevek" in instruction
    assert "csak a magyarra átírt választ" in instruction.casefold()
