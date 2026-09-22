import re


class GroundedFactualGuardError(RuntimeError):
    pass


def _normalize(value):
    return " ".join(str(value or "").strip().split()).casefold()


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
    unsupported = []
    for item in _critical_literals(answer):
        if _normalize(item) not in allowed:
            unsupported.append(item)
    return tuple(sorted(set(unsupported), key=str.casefold))


def guard_grounded_answer(
    client,
    model,
    user_prompt,
    answer,
    authority_text,
    *,
    trace=None,
    force_verify=False,
):
    draft = str(answer or "").strip()
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
                    "Do not add any name, date, number, price, version, URL, or factual claim "
                    "that is absent from the authorized evidence or user request. "
                    "Return only the repaired answer."
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
        raise GroundedFactualGuardError(
            "Grounded answer still contains unsupported factual literals: "
            + ", ".join(remaining[:6])
        )
    return repair
