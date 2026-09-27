from .context_guard import extract_entity_anchors
from .text_normalization import canonical_match_text


class CurrentTurnBindingError(RuntimeError):
    pass


def _fold(value):
    return canonical_match_text(value)


_QUESTION_WORDS = {
    "ki", "mi", "mit", "melyik", "mikor", "hol", "hogyan", "miert",
    "who", "what", "which", "when", "where", "how", "why",
    "wer", "was", "welche", "welcher", "welches", "wann", "wo", "wie", "warum",
}


def prompt_entity_anchors(user_prompt):
    anchors = []
    for item in extract_entity_anchors(user_prompt):
        folded = _fold(item).strip()
        if (
            folded
            and folded not in _QUESTION_WORDS
            and folded not in anchors
        ):
            anchors.append(folded)
    return tuple(anchors)


def _normalized_allowed_anchors(values):
    anchors = []
    for value in values or ():
        folded = _fold(value).strip()
        if folded and folded not in anchors:
            anchors.append(folded)
    return tuple(anchors)


def grounded_answer_mentions_current_entity(
    user_prompt,
    answer,
    *,
    allowed_entity_anchors=(),
):
    prompt_anchors = prompt_entity_anchors(user_prompt)
    allowed_anchors = _normalized_allowed_anchors(allowed_entity_anchors)
    anchors = tuple(dict.fromkeys(prompt_anchors + allowed_anchors))
    if not anchors:
        return True
    answer_folded = _fold(answer)
    return any(anchor in answer_folded for anchor in anchors)


def guard_current_turn_binding(
    client,
    model,
    user_prompt,
    answer,
    authority_text,
    *,
    trace=None,
    language_instruction="",
    allowed_entity_anchors=(),
):
    """
    Keep grounded factual-risk answers explicitly bound to the current request.

    This is entity-generic. It never knows specific QA names or works. Normally
    at least one explicit entity anchor from the current prompt must survive.
    For false-premise correction, callers may also provide entity surfaces that
    were mechanically extracted from the current request's authorized evidence;
    those are valid current-turn bindings too. One bounded repair is allowed.
    """
    draft = str(answer or "").strip()
    prompt_anchors = prompt_entity_anchors(user_prompt)
    evidence_anchors = _normalized_allowed_anchors(allowed_entity_anchors)
    if trace is not None:
        trace.add_metadata(
            current_turn_prompt_anchors=", ".join(prompt_anchors),
            current_turn_allowed_anchors=", ".join(evidence_anchors),
        )

    precheck_passed = (
        not prompt_anchors
        or grounded_answer_mentions_current_entity(
            user_prompt,
            draft,
            allowed_entity_anchors=evidence_anchors,
        )
    )
    if trace is not None:
        trace.add_metadata(
            current_turn_binding_precheck=(
                "pass" if precheck_passed else "repair_required"
            ),
        )
    if precheck_passed:
        return draft

    if trace is not None:
        trace.begin("current_turn_binding_repair")

    repaired = client.chat_once(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Repair the answer so it directly answers the CURRENT USER REQUEST. "
                    "The final answer must explicitly mention at least one subject/entity "
                    "from the current request OR one evidence-supported correction entity "
                    "explicitly listed below, rather than drifting to an adjacent topic. "
                    "Use ONLY the authorized evidence. Correct a false premise when the "
                    "evidence contradicts it. Keep the answer concise unless the user asked "
                    "for detail. Do not invent facts, names, dates, prices, versions, or URLs. "
                    + (" " + str(language_instruction).strip()
                       if str(language_instruction or "").strip() else "")
                    + " Return only the repaired answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"CURRENT USER REQUEST:\n{user_prompt}\n\n"
                    "ALLOWED EVIDENCE-SUPPORTED CORRECTION ENTITIES:\n"
                    + ("\n".join(evidence_anchors) if evidence_anchors else "(none)")
                    + "\n\n"
                    f"AUTHORIZED EVIDENCE:\n{authority_text}\n\n"
                    f"DRAFT ANSWER:\n{draft}"
                ),
            },
        ],
    ).strip()

    if trace is not None:
        trace.end("current_turn_binding_repair")

    repair_passed = bool(
        repaired
        and grounded_answer_mentions_current_entity(
            user_prompt,
            repaired,
            allowed_entity_anchors=evidence_anchors,
        )
    )
    if trace is not None:
        trace.add_metadata(
            current_turn_binding_repair_result=(
                "pass" if repair_passed else "failed"
            ),
        )
    if repair_passed:
        return repaired

    raise CurrentTurnBindingError(
        "Grounded answer lost current-turn entity binding after one repair."
    )
