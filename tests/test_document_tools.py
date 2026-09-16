from app.document_tools import (
    DOCUMENT_SYSTEM_PROMPT,
    EXCEL_SYSTEM_PROMPT,
    build_document_messages,
    build_excel_messages,
    topic_title,
)


def test_build_document_messages_uses_topic():
    messages = build_document_messages(
        "Create a short report about local AI privacy."
    )

    assert messages[0]["role"] == "system"
    assert messages[1] == {
        "role": "user",
        "content": "Create a short report about local AI privacy.",
    }


def test_build_document_messages_rejects_empty_topic():
    try:
        build_document_messages("   ")
    except ValueError as exc:
        assert "topic" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError")


def test_topic_title_uses_first_line_and_is_bounded():
    title = topic_title("My document title\nMore instructions", max_chars=10)
    assert title == "My documen"


def test_document_prompt_forbids_invented_metrics():
    prompt = DOCUMENT_SYSTEM_PROMPT.lower()
    assert "never invent benchmark scores" in prompt
    assert "hardware requirements" in prompt
    assert '"unknown"' in prompt


def test_excel_prompt_forbids_invented_metrics():
    prompt = EXCEL_SYSTEM_PROMPT.lower()
    assert "never invent benchmark scores" in prompt
    assert "not provided" in prompt
    messages = build_excel_messages("Compare local coding models.")
    assert messages[0]["content"] == EXCEL_SYSTEM_PROMPT
