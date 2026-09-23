"""Small deterministic helpers for the direct-fact fast path.

The helpers deliberately make no claim about a specific person, work, band, or
other entity.  Their role is limited to shaping an already-classified lookup and
checking whether its evidence includes the kind of fact the user asked for.
"""

import re

from .question_semantics import analyze_question
from .request_semantics import identity_lookup_subject
from .text_normalization import canonical_match_text


def _clean(value):
    return " ".join(str(value or "").split())


def _fold(value):
    return canonical_match_text(_clean(value))


def _marked_title(prompt):
    """Extract a title explicitly marked by quotes or title wording, if present."""
    raw = _clean(prompt)
    quoted = re.search(r"[\"'“”„](.{2,120}?)[\"'“”„]", raw)
    if quoted:
        return _clean(quoted.group(1))

    patterns = (
        r"(?:\ba\s+|\baz\s+)(.+?)\s+(?:c[ií]m[űu]|c\.)\s+(?:vers(?:et)?|m[űu](?:vet)?|konyv(?:et)?|regeny(?:t)?)\b",
        r"(?:\bthe\s+)?(.+?)\s+(?:titled|called)\s+(?:work|book|poem|novel)\b",
        r"(.+?)\s+(?:mit dem titel|namens)\s+",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = _clean(match.group(1))
            # Limit to the last title-like clause.  This removes a preceding
            # question word or alleged person without relying on their identity.
            candidate = re.split(
                r"\b(?:[ií]rta|wrote|authored|created|schrieb)\b",
                candidate,
                flags=re.IGNORECASE,
            )[-1].strip()
            # In "Mikor írta a Szerző az Ének c. verset?" the first
            # article starts the alleged author clause.  The final article is
            # the explicitly marked work title; taking it is a structural
            # parse, not a general typo/name correction.
            article_parts = re.split(
                r"\s+(?:a|az)\s+",
                candidate,
                flags=re.IGNORECASE,
            )
            if len(article_parts) > 1:
                candidate = article_parts[-1].strip()
            if 2 <= len(candidate) <= 120:
                return candidate
    return ""


def requested_fact_relation(prompt):
    """Classify the relation behind a requested fact without extracting entities."""
    semantic_relation = analyze_question(prompt).relation
    if semantic_relation == "event_date":
        return "event"
    if semantic_relation in {
        "authorship", "authorship_creation", "creation", "formation", "birth",
    }:
        if semantic_relation in {"authorship", "authorship_creation"}:
            return "creation"
        return semantic_relation

    folded = _fold(prompt)
    relation_patterns = (
        ("creation", (
            r"\b(?:irta|megirta|keletkezett|keszult)\b",
            r"\b(?:wrote|written|authored|composed|created)\b",
            r"\b(?:schrieb|verfasste|entstand)\b",
        )),
        ("formation", (
            r"\b(?:alakult|megalakult|letrejott)\b",
            r"\b(?:formed|founded|established)\b",
            r"\b(?:gegrundet|entstand)\b",
        )),
        ("birth", (
            r"\b(?:szuletett|born|geboren)\b",
        )),
        ("event", (
            r"\b(?:tortent|happened|occurred|geschah)\b",
        )),
    )
    for relation, patterns in relation_patterns:
        if any(re.search(pattern, folded) for pattern in patterns):
            return relation
    return "general"


def derive_premise_neutral_query(prompt, requested_fact="general"):
    """Return a conservative host-side direct-fact query and a strategy label.

    A neutral query is only used when the target is explicitly delimited.  For
    free-form questions, returning the validated original request is safer than
    guessing an entity boundary.
    """
    clean = _clean(prompt)
    identity_subject = identity_lookup_subject(clean)
    if identity_subject:
        return identity_subject, "identity_lookup_subject"

    title = _marked_title(clean)
    if not title:
        return clean, "validated_original"

    relation = requested_fact_relation(clean)
    temporal_suffixes = {
        "creation": "composition writing date year",
        "formation": "formation founding date year",
        "birth": "birth date year",
        "event": "event date year",
        "general": "date year",
    }
    suffixes = {
        "temporal": temporal_suffixes[relation],
        "location": "location place where",
        "quantity": "number quantity",
        "current_value": "current latest value",
        "version": "latest version release",
        "person_relation": "author creator founder",
        "value": "fact information",
    }
    suffix = suffixes.get(str(requested_fact or "general"), "fact information")
    return f"{title} {suffix}", "premise_neutral_title_relation"


def targeted_fact_refinement_query(prompt, requested_fact="general"):
    """Derive one stricter, bounded follow-up query after insufficient evidence."""
    clean = _clean(prompt)
    title = _marked_title(clean)
    if not title or str(requested_fact or "") != "temporal":
        return ""

    suffixes = {
        "creation": "original composition year",
        "formation": "formation year",
        "birth": "birth year",
        "event": "event date",
        "general": "date year",
    }
    return f"{title} {suffixes[requested_fact_relation(clean)]}"


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


def _temporal_relation_supported(text, relation):
    folded = _fold(text)
    markers = {
        "creation": (
            "irta", "megirta", "keletkez", "keszult", "wrote", "written",
            "authored", "composed", "created", "schrieb", "verfasste",
        ),
        "formation": (
            "alakult", "megalakult", "letrejott", "formed", "founded",
            "established", "gegrundet",
        ),
        "birth": ("szuletett", "born", "geboren"),
        "event": ("tortent", "happened", "occurred", "geschah"),
    }
    expected = markers.get(relation)
    return True if not expected else any(marker in folded for marker in expected)


def requested_fact_supported(payload, requested_fact="general", request_text=""):
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
        "identity": r"(?i)\b(?:is|was|known|musician|artist|actor|writer|band|egy|az|zen[ée]sz|eloado|sz[ií]nész|iro)\b",
    }
    pattern = checks.get(requested_fact)
    if not pattern or not re.search(pattern, text):
        return not pattern

    if requested_fact != "temporal":
        return True

    relation = requested_fact_relation(request_text)
    if relation == "general":
        return True

    # The date and requested relation must occur within the same result. A
    # publication/edition year alone cannot satisfy a creation-date question.
    for item in dict(payload or {}).get("results") or []:
        item_text = "\n".join((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
        if re.search(pattern, item_text) and _temporal_relation_supported(
            item_text,
            relation,
        ):
            return True
    return False


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
