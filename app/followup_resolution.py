from dataclasses import dataclass
import re

from .text_normalization import canonical_match_text


_SHORT_FOLLOWUP_PHRASES = frozenset({
    "why", "and", "how", "how much", "which", "source",
    "what does this mean", "miert", "es", "hogyan", "mennyi",
    "melyik", "forras", "ez mit jelent",
})


def _fold(value):
    return canonical_match_text(value)


def _has_lexical_term(value):
    return bool(re.search(r"[^\W_]{2,}", str(value or ""), flags=re.UNICODE))


def is_contextual_short_followup(value):
    """Whether an input needs an immediately preceding turn to be meaningful."""
    raw = " ".join(str(value or "").split())
    folded = _fold(raw)
    if not raw or not _has_lexical_term(raw):
        return True
    if folded in _SHORT_FOLLOWUP_PHRASES:
        return True
    words = set(folded.split())
    return len(words) <= 5 and bool(words.intersection({
        "erre", "arra", "that", "this", "it",
    }))


def _previous_turn(messages):
    previous_assistant = ""
    previous_user = ""
    for message in reversed(list(messages or [])):
        role = str(message.get("role") or "")
        content = " ".join(str(message.get("content") or "").split())
        if not content:
            continue
        if not previous_assistant and role == "assistant":
            previous_assistant = content[:1600]
            continue
        if previous_assistant and role == "user":
            previous_user = content[:1200]
            break
    return previous_user, previous_assistant


def _clarification(value):
    folded = _fold(value)
    if any(marker in folded for marker in ("miert", "hogyan", "mennyi", "melyik", "forras", "ez ")):
        return "Kérlek, írd le, mire utalsz, vagy add meg az előző kérdést is."
    return "Please add a little context so I know what you would like to continue."


def _resolved_intent(followup, previous_user, previous_assistant):
    folded = _fold(followup)
    if not _has_lexical_term(followup):
        instruction = "Explain the previous answer more clearly"
    elif folded in {"miert", "why"}:
        instruction = "Explain why the answer to the previous question is correct"
    elif folded in {"hogyan", "how"}:
        instruction = "Explain how to address the previous question"
    elif folded in {"mennyi", "how much"}:
        instruction = "Give the requested amount for the previous question"
    elif folded in {"melyik", "which"}:
        instruction = "Identify which option answers the previous question"
    elif folded in {"forras", "source"}:
        instruction = "Provide sources for the previous answer"
    else:
        instruction = f"Answer this follow-up in the previous context: {followup}"

    return (
        f"{instruction}. Previous user question: {previous_user}. "
        f"Previous assistant answer: {previous_assistant}"
    )[:3600]


@dataclass(frozen=True)
class FollowupResolution:
    original_text: str
    resolved_intent: str
    status: str
    clarification: str = ""

    @property
    def needs_clarification(self):
        return self.status == "clarification"


def resolve_contextual_followup(user_text, messages):
    raw_original = str(user_text or "")
    normalized = " ".join(raw_original.split())
    if not is_contextual_short_followup(normalized):
        return FollowupResolution(raw_original, raw_original, "direct")

    previous_user, previous_assistant = _previous_turn(messages)
    if not previous_user or not previous_assistant:
        return FollowupResolution(
            raw_original,
            "",
            "clarification",
            _clarification(normalized),
        )

    return FollowupResolution(
        raw_original,
        _resolved_intent(normalized, previous_user, previous_assistant),
        "resolved",
    )
