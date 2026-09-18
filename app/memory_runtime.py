from .memory_extractor import extract_explicit_memories


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
