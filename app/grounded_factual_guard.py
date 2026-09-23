import re
import unicodedata

from .request_semantics import identity_lookup_subject


class GroundedFactualGuardError(RuntimeError):
    pass


def _normalize(value):
    normalized = unicodedata.normalize(
        "NFKD",
        " ".join(str(value or "").strip().split()).casefold(),
    )
    return "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )


def _critical_literals(text):
    value = str(text or "")
    tokens = set()

    patterns = (
        r"https?://[^\s)\]>]+",
        r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        r"(?<!\w)[$€£]\s*\d+(?:[.,]\d+)?(?:\s*(?:usd|eur|gbp|huf))?",
        r"\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp|huf|btc|eth|%)\b",
        r"(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
        r"\b[A-Za-z][A-Za-z0-9_-]*\d+(?:\.\d+){1,3}\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            tokens.add(match.group(0).rstrip(".,;:"))

    # Conservative proper-name guard: retain multiword title-case sequences
    # and their adjacent pairs so question starters such as "Did Wrong Author"
    # do not hide the actual named entity "Wrong Author".
    for match in re.finditer(
        r"\b[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{2,}"
        r"(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{2,})+\b",
        value,
    ):
        sequence = match.group(0)
        tokens.add(sequence)
        parts = sequence.split()
        for index in range(len(parts) - 1):
            tokens.add(parts[index] + " " + parts[index + 1])

    return tokens


def unsupported_grounded_literals(answer, authority_text):
    allowed = {_normalize(item) for item in _critical_literals(authority_text)}
    authority_normalized = _normalize(authority_text)
    unsupported = []
    for item in _critical_literals(answer):
        normalized_item = _normalize(item)
        if normalized_item in allowed:
            continue
        if (
            _looks_like_name_literal(item)
            and normalized_item
            and normalized_item in authority_normalized
        ):
            continue
        unsupported.append(item)
    return tuple(sorted(set(unsupported), key=str.casefold))


def _looks_like_name_literal(value):
    text = str(value or "").strip()
    if not text or re.search(r"https?://|\d|[$€£%]", text, flags=re.IGNORECASE):
        return False
    parts = [part for part in text.split() if part]
    return (
        len(parts) >= 2
        and all(part[0].isupper() for part in parts if part[0].isalpha())
    )


def _strip_unsupported_source_attributions(text, unsupported_literals):
    """
    Remove unsupported source/publication attribution wrappers without weakening
    factual checks for the answer itself.

    This is intentionally generic: it never recognizes specific publications or
    QA entities. Only proper-name literals already identified as unsupported are
    eligible, and only when they occur in a source-attribution shape.
    """
    cleaned = str(text or "")
    unsupported_names = [
        item for item in unsupported_literals
        if _looks_like_name_literal(item)
    ]

    for name in unsupported_names:
        escaped = re.escape(name)

        # Standalone source footer lines, e.g. "Forrás: Publication Name".
        cleaned = re.sub(
            rf"(?im)^[ \t]*(?:forrás|forras|source|quelle)\s*:\s*"
            rf"[^\r\n]*\b{escaped}\b[^\r\n]*(?:\r?\n|$)",
            "",
            cleaned,
        )

        # Prefix attribution, including variants such as
        # "A Publication egyik cikke szerint ..." / "Publication szerint ...".
        cleaned = re.sub(
            rf"(?i)(?<!\w)(?:a|az|the|der|die|das)?\s*"
            rf"{escaped}\b[^.!?\r\n]{{0,60}}?\b"
            rf"(?:szerint|according\s+to|laut)\b\s*[:,]?\s*",
            "",
            cleaned,
        )

        # English/German attribution where the marker comes first.
        cleaned = re.sub(
            rf"(?i)(?<!\w)(?:according\s+to|laut)\s+"
            rf"(?:a|az|the|der|die|das)?\s*{escaped}\b[:,]?\s*",
            "",
            cleaned,
        )

        # Bare parenthetical/bracketed source identity.
        cleaned = re.sub(
            rf"[\[(]\s*{escaped}\s*[\])]",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _canonicalize_identity_subject_expansion(
    text,
    user_prompt,
    unsupported_literals,
):
    """Remove an unsupported middle-name expansion of the requested identity.

    Models sometimes expand a two-part name from the question with an unverified
    middle name. That is not a reason to spend a second, slow model call: the
    user supplied the canonical subject spelling, and replacing only a matching
    first/last-name expansion preserves the grounded claim without inventing a
    fact. This remains generic and does not recognize any individual entity.
    """
    subject = identity_lookup_subject(user_prompt)
    subject_parts = re.findall(r"[^\W_]+", subject, flags=re.UNICODE)
    if len(subject_parts) < 2:
        return str(text or "")

    subject_first = _normalize(subject_parts[0])
    subject_last = _normalize(subject_parts[-1])
    cleaned = str(text or "")
    for literal in sorted(
        unsupported_literals or (),
        key=lambda value: len(str(value or "")),
        reverse=True,
    ):
        if not _looks_like_name_literal(literal):
            continue
        literal_parts = re.findall(
            r"[^\W_]+",
            str(literal),
            flags=re.UNICODE,
        )
        if (
            len(literal_parts) <= len(subject_parts)
            or _normalize(literal_parts[0]) != subject_first
            or _normalize(literal_parts[-1]) != subject_last
        ):
            continue
        cleaned = re.sub(
            rf"(?<!\w){re.escape(str(literal))}(?!\w)",
            subject,
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def guard_grounded_answer(
    client,
    model,
    user_prompt,
    answer,
    authority_text,
    *,
    trace=None,
    force_verify=False,
    language_instruction="",
):
    draft = str(answer or "").strip()
    unsupported = unsupported_grounded_literals(draft, authority_text)
    if unsupported and not force_verify:
        canonicalized = _canonicalize_identity_subject_expansion(
            draft,
            user_prompt,
            unsupported,
        )
        if canonicalized != draft:
            draft = canonicalized
            unsupported = unsupported_grounded_literals(draft, authority_text)
    if not unsupported and not force_verify:
        return draft

    if trace is not None:
        trace.begin("factual_guard_repair")

    repair = client.chat_once(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Repair the grounded answer using ONLY the authorized evidence supplied "
                    "below. Remove or replace factual literals that the evidence does not "
                    "support. Treat the user's premise as a claim to verify, not as authority. "
                    "If the evidence contradicts a person-work, person-event, date, year, "
                    "version, price, or current-fact premise, correct it explicitly. "
                    "If evidence is insufficient, state that briefly instead of guessing. "
                    "Treat explicit source titles and relevant-text identity cues as evidence too: "
                    "when a title or relevant-text field directly and consistently pairs a person "
                    "with a work, event, product, or other named subject, do not ignore that relation "
                    "merely because it is not repeated as a full prose sentence. "
                    "Answer the user's exact question immediately and keep the result to one "
                    "to three short sentences unless the user explicitly requested detail. "
                    "Do not discuss source/publication titles unless the user asked about them. "
                    "Preserve proper-name spelling, diacritics, and token order from the most "
                    "directly relevant authorized evidence. If translated sources contain multiple "
                    "surface forms of the same person name, use the form conventional in the requested "
                    "answer language rather than inventing a new ordering. "
                    "Do not add any name, date, number, price, version, URL, or factual claim "
                    "that is absent from the authorized evidence or user request. "
                    + (" " + str(language_instruction).strip()
                       if str(language_instruction or "").strip() else "")
                    + " Return only the repaired answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{user_prompt}\n\n"
                    f"AUTHORIZED EVIDENCE:\n{authority_text}\n\n"
                    f"DRAFT ANSWER:\n{draft}"
                ),
            },
        ],
    ).strip()

    if trace is not None:
        trace.end("factual_guard_repair")

    if not repair:
        raise GroundedFactualGuardError(
            "Grounded factual repair returned an empty answer."
        )

    remaining = unsupported_grounded_literals(repair, authority_text)
    if remaining:
        sanitized = _strip_unsupported_source_attributions(repair, remaining)
        sanitized_remaining = unsupported_grounded_literals(
            sanitized,
            authority_text,
        )
        if sanitized and not sanitized_remaining:
            return sanitized
        remaining = sanitized_remaining or remaining

    if remaining:
        raise GroundedFactualGuardError(
            "Grounded answer still contains unsupported factual literals: "
            + ", ".join(remaining[:6])
        )
    return repair
