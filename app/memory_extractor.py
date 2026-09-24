import json
import re

from .memory_store import ALLOWED_CATEGORIES, is_secret_memory_candidate


MAX_EXPLICIT_MEMORIES = 8
MAX_RESPONSE_MEMORY_SOURCE_CHARS = 12_000

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


PERSON_RELATION_SUFFIX_HU = {
    "fia": "son_of",
    "lánya": "daughter_of",
    "lanya": "daughter_of",
    "férje": "husband_of",
    "ferje": "husband_of",
    "felesége": "wife_of",
    "felesege": "wife_of",
    "barátnője": "girlfriend_of",
    "baratnoje": "girlfriend_of",
    "barátja": "boyfriend_of",
    "baratja": "boyfriend_of",
    "anyja": "mother_of",
    "apja": "father_of",
    "testvére": "sibling_of",
    "testvere": "sibling_of",
    "párja": "partner_of",
    "parja": "partner_of",
}


def _explicit_memory_body(user_text):
    body = re.sub(
        r"^.*?\b(?:jegyezd\s+meg|emlekezz|emlékezz|remember(?:\s+that)?)\b\s*",
        "",
        user_text,
        count=1,
        flags=re.IGNORECASE,
    )
    return re.sub(r"^(?:,?\s*hogy\s+)", "", body, count=1, flags=re.IGNORECASE)


def _explicit_person_relationship_memories(user_text):
    """Extract explicit relationships between two named people without assigning them to USER."""
    if not is_explicit_memory_request(user_text):
        return []

    body = _clean(_explicit_memory_body(user_text)).strip(" ,.;:!?")
    relation_terms = "|".join(
        sorted(
            (re.escape(term) for term in PERSON_RELATION_SUFFIX_HU),
            key=len,
            reverse=True,
        )
    )
    match = re.match(
        rf"^(?P<subject>.+?)\s+(?P<related>[^\s,.;:!?]+)\s+"
        rf"(?P<relation>{relation_terms})$",
        body,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    subject = _clean(match.group("subject")).strip(" ,.;:!?")
    related = _clean(match.group("related")).strip(" ,.;:!?")
    relation = PERSON_RELATION_SUFFIX_HU.get(match.group("relation").lower())
    if not subject or not related or not relation:
        return []

    return [{
        "category": "USER_PROFILE",
        "scope": "USER",
        "subject": subject,
        "key": relation,
        "value": related,
    }]


def _explicit_relationship_memories(user_text):
    """Deterministically extract common user relationships from explicit memory requests."""
    if not is_explicit_memory_request(user_text):
        return []

    relation_terms = "|".join(
        sorted((re.escape(term) for term in RELATIONSHIP_TO_USER), key=len, reverse=True)
    )
    relation_first = re.compile(
        rf"^(?:a\s+)?(?P<relation>{relation_terms})\s+(?P<name>.+)$",
        re.IGNORECASE,
    )
    relation_last = re.compile(
        rf"^(?P<name>.+?)\s+(?:a\s+)?(?P<relation>{relation_terms})$",
        re.IGNORECASE,
    )

    body = _explicit_memory_body(user_text)

    memories = []
    seen = set()
    for clause in re.split(r"\s+(?:és|es|and)\s+", body, flags=re.IGNORECASE):
        clause = _clean(clause).strip(" ,.;:!?")
        if not clause:
            continue

        match = relation_first.match(clause) or relation_last.match(clause)
        if not match:
            continue

        relation_token = match.group("relation").lower()
        name = _clean(match.group("name")).strip(" ,.;:!?")
        relation = RELATIONSHIP_TO_USER.get(relation_token)
        if not name or not relation:
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
        + _explicit_person_relationship_memories(user_text)
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
                "explicitly makes the fact project-specific. Use relationship_to_user ONLY "
                "when the named person's relationship is explicitly to the human user. "
                "For relationships between two other people use directional keys such as "
                "son_of, daughter_of, girlfriend_of, boyfriend_of, partner_of, mother_of, "
                "or father_of, with the related person as the value. Use stable concise keys "
                "such as preferred_shell. "
                "Never invent missing information. Return only data matching the supplied JSON schema."
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


def extract_response_memories(client, model, response_text):
    """Normalize an explicitly selected assistant response into durable candidates."""
    response_text = _clean(response_text)
    if not response_text:
        return []
    response_text = response_text[:MAX_RESPONSE_MEMORY_SOURCE_CHARS]

    raw = client.chat_once(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "The user explicitly selected an assistant response to save to long-term "
                    "memory. Extract only concrete, reusable facts, decisions, preferences, "
                    "rules, lessons, or project state stated in that response. Do not save "
                    "speculation, citations, incidental web text, or conversational filler. "
                    "Create atomic records using USER_PROFILE, PROJECT, PREFERENCE, RULE, "
                    "LESSON, or WORKING. Use concise stable keys. Return an empty list if "
                    "nothing is suitable. Never invent missing information. Return only data "
                    "matching the supplied JSON schema."
                ),
            },
            {"role": "user", "content": response_text},
        ],
        response_format=MEMORY_EXTRACTION_SCHEMA,
    )
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("memory extractor returned invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"memories"}:
        raise ValueError("memory extractor payload contains unexpected fields")
    items = payload.get("memories")
    if not isinstance(items, list):
        raise ValueError("memory extractor memories must be a list")
    if len(items) > MAX_EXPLICIT_MEMORIES:
        raise ValueError("too many explicit memories in one response")
    return [validate_memory_candidate(item) for item in items]
