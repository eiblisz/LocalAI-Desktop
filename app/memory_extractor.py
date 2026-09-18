import json
import re

from .memory_store import ALLOWED_CATEGORIES, is_secret_memory_candidate


MAX_EXPLICIT_MEMORIES = 8

MEMORY_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "maxItems": MAX_EXPLICIT_MEMORIES,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "scope": {"type": "string"},
                    "subject": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": [
                    "category",
                    "scope",
                    "subject",
                    "key",
                    "value",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memories"],
    "additionalProperties": False,
}

_MEMORY_FIELDS = {"category", "scope", "subject", "key", "value"}

_EXPLICIT_MEMORY_PATTERNS = (
    re.compile(r"\bjegyezd\s+meg\b", re.IGNORECASE),
    re.compile(r"\bemlekezz\b", re.IGNORECASE),
    re.compile(r"\bemlékezz\b", re.IGNORECASE),
    re.compile(r"\bremember(?:\s+that)?\b", re.IGNORECASE),
)


def _clean(value):
    return " ".join(str(value or "").strip().split())


def is_explicit_memory_request(text):
    text = _clean(text)
    if not text:
        return False
    return any(pattern.search(text) for pattern in _EXPLICIT_MEMORY_PATTERNS)


def validate_memory_candidate(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("memory candidate must be an object")

    unexpected = set(candidate) - _MEMORY_FIELDS
    if unexpected:
        raise ValueError("memory candidate contains unexpected fields")

    category = _clean(candidate.get("category")).upper()
    scope = _clean(candidate.get("scope"))
    subject = _clean(candidate.get("subject"))
    key = _clean(candidate.get("key"))
    value = _clean(candidate.get("value"))

    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"invalid memory category: {category}")

    if not scope:
        raise ValueError("memory scope is required")
    if not subject:
        raise ValueError("memory subject is required")
    if not key:
        raise ValueError("memory key is required")
    if not value:
        raise ValueError("memory value is required")

    if len(scope) > 160:
        raise ValueError("memory scope is too long")
    if len(subject) > 160:
        raise ValueError("memory subject is too long")
    if len(key) > 160:
        raise ValueError("memory key is too long")
    if len(value) > 4000:
        raise ValueError("memory value is too long")

    if is_secret_memory_candidate(
        key=key,
        value=value,
        subject=subject,
    ):
        raise ValueError("secret memory candidate rejected")

    return {
        "category": category,
        "scope": scope,
        "subject": subject,
        "key": key,
        "value": value,
    }


SELF_NAME_PATTERNS = (
    re.compile(
        r"\b(?:az\s+én\s+nevem|az\s+en\s+nevem|a\s+nevem)\s+(?P<name>[^,.!?;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy\s+name\s+is\s+(?P<name>[^,.!?;]+)",
        re.IGNORECASE,
    ),
)


def _explicit_self_name_memories(user_text):
    if not is_explicit_memory_request(user_text):
        return []

    for pattern in SELF_NAME_PATTERNS:
        match = pattern.search(user_text)
        if not match:
            continue
        name = _clean(match.group("name")).strip(" ,.;:!?")
        if not name:
            return []
        return [{
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "USER",
            "key": "name",
            "value": name,
        }]
    return []


RELATIONSHIP_TO_USER = {
    "párom": "partner",
    "parom": "partner",
    "lányom": "daughter",
    "lanyom": "daughter",
    "fiam": "son",
    "férjem": "husband",
    "ferjem": "husband",
    "feleségem": "wife",
    "felesegem": "wife",
    "anyám": "mother",
    "anyam": "mother",
    "apám": "father",
    "apam": "father",
    "testvérem": "sibling",
    "testverem": "sibling",
}


def _explicit_relationship_memories(user_text):
    """Deterministically extract common user relationships from explicit memory requests."""
    if not is_explicit_memory_request(user_text):
        return []

    relation_terms = "|".join(
        sorted((re.escape(term) for term in RELATIONSHIP_TO_USER), key=len, reverse=True)
    )
    pattern = re.compile(
        rf"(?:\ba\s+)?(?P<relation>{relation_terms})\s+"
        rf"(?P<name>.+?)"
        rf"(?=(?:\s+(?:és|es|and)\s+(?:a\s+)?(?:{relation_terms})\b)|[,.!?;]|$)",
        re.IGNORECASE,
    )

    memories = []
    seen = set()
    for match in pattern.finditer(user_text):
        relation_token = match.group("relation").lower()
        name = _clean(match.group("name")).strip(" ,.;:!?")
        if not name:
            continue

        relation = RELATIONSHIP_TO_USER.get(relation_token)
        if not relation:
            continue

        identity = (name.casefold(), relation)
        if identity in seen:
            continue
        seen.add(identity)

        memories.append({
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": name,
            "key": "relationship_to_user",
            "value": relation,
        })

    return memories


def extract_explicit_memories(client, model, user_text):
    user_text = _clean(user_text)
    if not is_explicit_memory_request(user_text):
        return []

    deterministic_memories = (
        _explicit_self_name_memories(user_text)
        + _explicit_relationship_memories(user_text)
    )
    if deterministic_memories:
        return [validate_memory_candidate(item) for item in deterministic_memories]

    messages = [
        {
            "role": "system",
            "content": (
                "Extract ONLY information that the user explicitly asked to remember. "
                "Do not infer additional facts. Split multiple independent facts into "
                "separate atomic memory records. Preserve names exactly as provided. "
                "Use one category from USER_PROFILE, PROJECT, PREFERENCE, RULE, LESSON, "
                "or WORKING. Use scope USER for general personal facts unless the user "
                "explicitly makes the fact project-specific. Use stable concise keys "
                "such as relationship_to_user or preferred_shell. Never invent missing "
                "information. Return only data matching the supplied JSON schema."
            ),
        },
        {
            "role": "user",
            "content": user_text,
        },
    ]

    raw = client.chat_once(
        model=model,
        messages=messages,
        response_format=MEMORY_EXTRACTION_SCHEMA,
    )

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("memory extractor returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("memory extractor payload must be an object")

    if set(payload) != {"memories"}:
        raise ValueError("memory extractor payload contains unexpected fields")

    items = payload.get("memories")
    if not isinstance(items, list):
        raise ValueError("memory extractor memories must be a list")

    if len(items) > MAX_EXPLICIT_MEMORIES:
        raise ValueError("too many explicit memories in one request")

    return [validate_memory_candidate(item) for item in items]
