import re

from .task_constraints import TaskConstraints
from .text_normalization import canonical_match_text


class ContextDriftError(RuntimeError):
    pass


_COMMON_CAPITALIZED = {
    "A","Az","Egy","Es","És","Ha","Hogy","Ki","Mi","Melyik","Mennyi","Mikor","Hol",
    "The","This","That","What","Which","Who","How","When","Where",
    "Der","Die","Das","Ein","Eine","Was","Welche","Wer","Wie","Wann","Wo",
}

_REFERENTIAL_MARKERS = (
    "ennek","annak","ebből","ebbol","abból","abbol","erre","arra","ezt","azt",
    "ilyen","ilyet","ugyanez","ugyanaz","it","its","this","that","these","those",
    "dies","diese","dieser","das","davon","dafür","dafur",
)


def _fold(value):
    return canonical_match_text(value)


def is_referential_followup(text):
    folded = _fold(text)
    return any(re.search(rf"\b{re.escape(_fold(marker))}\b", folded) for marker in _REFERENTIAL_MARKERS)


def extract_entity_anchors(text):
    text = str(text or "")
    anchors = set()

    for token in re.findall(r"\b[A-Za-z0-9][A-Za-z0-9_.:+/-]*\b", text):
        if re.search(r"[A-Za-z]", token) and re.search(r"\d", token):
            anchors.add(token)

    for token in re.findall(r"\b[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű0-9_-]{2,}\b", text):
        if token not in _COMMON_CAPITALIZED:
            anchors.add(token)

    return tuple(sorted(anchors, key=str.casefold))


def _authority_text(current_prompt, constraints):
    parts = [str(current_prompt or "").strip()]
    if isinstance(constraints, TaskConstraints):
        parent = str(constraints.parent_intent or "").strip()
        if parent:
            parts.append(parent)
    return "\n".join(part for part in parts if part)


def stale_subject_substitution(
    current_prompt,
    response_text,
    messages,
    *,
    constraints=None,
):
    if is_referential_followup(current_prompt):
        return ()

    authority_anchors = set(extract_entity_anchors(_authority_text(current_prompt, constraints)))
    if not authority_anchors:
        return ()

    prior_user_text = "\n".join(
        str(item.get("content") or "")
        for item in (messages or [])
        if item.get("role") == "user"
        and str(item.get("content") or "").strip() != str(current_prompt or "").strip()
    )
    stale_anchors = set(extract_entity_anchors(prior_user_text)) - authority_anchors
    if not stale_anchors:
        return ()

    response_folded = _fold(response_text)
    current_hits = {
        anchor for anchor in authority_anchors
        if _fold(anchor) in response_folded
    }
    stale_hits = {
        anchor for anchor in stale_anchors
        if _fold(anchor) in response_folded
    }

    if stale_hits and not current_hits:
        return tuple(sorted(stale_hits, key=str.casefold))
    return ()


def _repair_messages(
    current_prompt,
    response_text,
    messages,
    stale_anchors,
    *,
    constraints=None,
):
    authority = _authority_text(current_prompt, constraints)
    stale = ", ".join(stale_anchors)
    return [
        {
            "role": "system",
            "content": (
                "Repair the draft so it answers the CURRENT/PARENT task and does not drift "
                "to an unrelated subject from earlier conversation history. "
                f"Stale unrelated subject anchors detected: {stale}. "
                "Do not add new facts. Preserve supported numbers, URLs, names, and factual "
                "claims exactly when they remain relevant. Return only the repaired answer."
            ),
        },
        {
            "role": "user",
            "content": (
                "CURRENT/PARENT TASK:\n"
                + authority
                + "\n\nDRAFT TO REPAIR:\n"
                + str(response_text or "")
            ),
        },
    ]


def guard_context_response(
    client,
    model,
    current_prompt,
    response_text,
    messages,
    *,
    constraints=None,
    control=None,
):
    draft = str(response_text or "").strip()
    if not draft:
        return draft

    stale = stale_subject_substitution(
        current_prompt,
        draft,
        messages,
        constraints=constraints,
    )
    if not stale:
        return draft

    repair_messages = _repair_messages(
        current_prompt,
        draft,
        messages,
        stale,
        constraints=constraints,
    )

    kwargs = {}
    if control is not None:
        kwargs["control"] = control

    try:
        repaired = client.chat_once(
            model=model,
            messages=repair_messages,
            **kwargs,
        ).strip()
    except TypeError as exc:
        if "control" not in str(exc):
            raise
        repaired = client.chat_once(
            model=model,
            messages=repair_messages,
        ).strip()

    stale_after = stale_subject_substitution(
        current_prompt,
        repaired,
        messages,
        constraints=constraints,
    )
    if repaired and not stale_after:
        return repaired

    raise ContextDriftError(
        "Response rejected after one bounded context-drift repair attempt: "
        + ", ".join(stale_after or stale)
    )
