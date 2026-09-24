from .memory_extractor import extract_explicit_memories, extract_response_memories


def semantic_memory_context_lines(memories):
    """Serialize approved memory facts without exposing internal storage labels."""
    lines = []
    for memory in memories:
        category = str(memory.get("category", "")).strip()
        subject = str(memory.get("subject", "")).strip()
        key = str(memory.get("key", "")).strip()
        value = str(memory.get("value", "")).strip()
        if not value:
            continue

        normalized_key = key.casefold()
        if category == "USER_PROFILE" and normalized_key in {
            "name",
            "user_name",
            "preferred_name",
        }:
            lines.append(f"- Durable user fact: the user's name is {value}.")
            continue

        if category == "USER_PROFILE" and normalized_key == "relationship_to_user":
            lines.append(f"- Durable user fact: {subject} is the user's {value}.")
            continue

        if category == "USER_PROFILE" and normalized_key.endswith("_of"):
            relation_text = normalized_key.replace("_", " ")
            lines.append(
                f"- Durable person fact: {subject} is the {relation_text} {value}. "
                "This is a relationship between two people, not a relationship to the user."
            )
            continue

        lines.append(f"- Durable memory value: {value}")
    return lines


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
