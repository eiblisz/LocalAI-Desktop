"""Small deterministic helpers for the direct-fact fast path.

The helpers deliberately make no claim about a specific person, work, band, or
other entity.  Their role is limited to shaping an already-classified lookup and
checking whether its evidence includes the kind of fact the user asked for.
"""

import re
import unicodedata


def _clean(value):
    return " ".join(str(value or "").split())


def _fold(value):
    normalized = unicodedata.normalize("NFKD", _clean(value).casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _marked_title(prompt):
    """Extract a title explicitly marked by quotes or title wording, if present."""
    raw = _clean(prompt)
    quoted = re.search(r"[\"'“”„](.{2,120}?)[\"'“”„]", raw)
    if quoted:
        return _clean(quoted.group(1))

    patterns = (
        r"(?:\ba\s+|\baz\s+)(.+?)\s+c[ií]m[űu]\s+(?:vers(?:et)?|m[űu](?:vet)?|konyv(?:et)?|regeny(?:t)?)\b",
        r"(?:\bthe\s+)?(.+?)\s+(?:titled|called)\s+(?:work|book|poem|novel)\b",
        r"(.+?)\s+(?:mit dem titel|namens)\s+",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = _clean(match.group(1))
            # Limit to the last title-like clause.  This removes a preceding
            # question word or alleged person without relying on their identity.
            candidate = re.split(r"\b(?:irta|irta|wrote|authored|created|schrieb)\b", candidate, flags=re.IGNORECASE)[-1].strip()
            if 2 <= len(candidate) <= 120:
                return candidate
    return ""


def derive_premise_neutral_query(prompt, requested_fact="general"):
    """Return a conservative host-side direct-fact query and a strategy label.

    A neutral query is only used when the target is explicitly delimited.  For
    free-form questions, returning the validated original request is safer than
    guessing an entity boundary.
    """
    clean = _clean(prompt)
    title = _marked_title(clean)
    if not title:
        return clean, "validated_original"

    suffixes = {
        "temporal": "creation publication date year",
        "location": "location place where",
        "quantity": "number quantity",
        "current_value": "current latest value",
        "version": "latest version release",
        "person_relation": "author creator founder",
        "value": "fact information",
    }
    suffix = suffixes.get(str(requested_fact or "general"), "fact information")
    return f"{title} {suffix}", "premise_neutral_title_relation"


def _evidence_text(payload):
    parts = []
    for item in dict(payload or {}).get("results") or []:
        parts.extend((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
    return "\n".join(parts)


def requested_fact_supported(payload, requested_fact="general"):
    """Whether provider snippets/page text contain a usable fact-shaped signal."""
    text = _evidence_text(payload)
    if not _clean(text):
        return False

    requested_fact = str(requested_fact or "general")
    checks = {
        "temporal": r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        "quantity": r"\b\d+(?:[.,]\d+)?\b",
        "version": r"(?i)\bv?\d+(?:\.\d+){1,3}\b|\b(?:version|release|verzi[oó]|kiad[aá]s)\b",
        "current_value": r"\b\d+(?:[.,]\d+)?\b",
        "location": r"(?i)\b(?:in|at|from|located|helye|itt|ban|ben)\b",
        "person_relation": r"(?i)\b(?:wrote|written|author|creator|founded|founded by|[ií]rta|szerz[őo]|alkotta|alap[ií]totta)\b",
    }
    pattern = checks.get(requested_fact)
    return bool(re.search(pattern, text)) if pattern else True


def deterministic_hungarian_fact_fallback(authority_text, requested_fact="general"):
    """Return a minimal Hungarian fallback only for an explicit supported literal.

    This is intentionally not a translator or answer generator.  It is used
    only after one failed language repair, and only when the requested fact is
    an unambiguous host-extractable literal already present in evidence.
    """
    text = str(authority_text or "")
    requested_fact = str(requested_fact or "general")
    patterns = {
        "temporal": r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        "quantity": r"\b\d+(?:[.,]\d+)?\b",
        "current_value": r"\b\d+(?:[.,]\d+)?\b",
    }
    pattern = patterns.get(requested_fact)
    if not pattern:
        return ""
    match = re.search(pattern, text)
    if not match:
        return ""
    value = match.group(0)
    if requested_fact == "temporal":
        return f"A rendelkezésre álló források alapján a kért időpont: {value}."
    return f"A rendelkezésre álló források alapján a kért érték: {value}."
