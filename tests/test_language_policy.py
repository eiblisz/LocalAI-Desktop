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
