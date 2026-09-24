from .memory_extractor import extract_explicit_memories, extract_response_memories


def remember_explicit_request(
    client,
    model,
    user_text,
    store,
    *,
    source_chat_id=None,
):
    """Extract and persist explicit user memories through the canonical host store."""
    candidates = extract_explicit_memories(
        client,
        model,
        user_text,
    )
    if not candidates:
        return []

    written = []
    for candidate in candidates:
        memory = store.remember_explicit(
            category=candidate["category"],
            scope=candidate["scope"],
            subject=candidate["subject"],
            key=candidate["key"],
            value=candidate["value"],
            source_chat_id=source_chat_id,
            source_excerpt=user_text,
            importance="IMPORTANT",
            confidence=1.0,
        )
        written.append(memory)

    return written


def remember_response(
    client,
    model,
    response_text,
    store,
    *,
    source_chat_id=None,
    source_message_id=None,
):
    candidates = extract_response_memories(client, model, response_text)
    source_excerpt = str(response_text or "").strip()[:2000]
    written = []
    for candidate in candidates:
        memory = store.remember_explicit(
            category=candidate["category"],
            scope=candidate["scope"],
            subject=candidate["subject"],
            key=candidate["key"],
            value=candidate["value"],
            source_chat_id=source_chat_id,
            source_excerpt=source_excerpt,
            source_type="response_remember",
            source_ref=source_message_id or source_chat_id,
            importance="IMPORTANT",
            confidence=1.0,
        )
        written.append(memory)
    return written
