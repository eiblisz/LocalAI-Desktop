from app.language_policy import detect_user_language, response_language_instruction


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
    assert "Hungarian" in instruction
    assert "Answer in Hungarian" in instruction
    assert "Do not switch to English" in instruction


def test_unknown_language_still_forbids_unrequested_switching():
    instruction = response_language_instruction("Zsofia?")
    assert "same language as the current user message" in instruction
    assert "Do not switch languages" in instruction


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

