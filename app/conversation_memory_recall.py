"""Safe deterministic recall from explicit user-provided conversation state.

This module is intentionally narrower than persistent/global memory.  It only
looks at already-authorized user messages from the current conversation and
returns a value when one unambiguous structural match is available.  Any
uncertainty falls through to the existing model path.
"""

from dataclasses import dataclass
import re

from .memory_store import is_secret_memory_candidate
from .response_guard import validate_response
from .text_normalization import canonical_match_text


_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", flags=re.UNICODE)

_QUESTION_MARKERS = {
    "mi", "melyik", "mennyi", "hany", "ki", "hol", "mikor", "hogyan",
    "what", "which", "who", "where", "when", "how", "wie", "was",
    "wer", "wo", "wann",
}

_NON_FACT_TOKENS = _QUESTION_MARKERS | {
    "a", "az", "es", "ebben", "ezen", "ennek", "itt", "aktualis",
    "beszelgetes", "beszelgetesben", "beszelgetesnek", "chat", "chatben",
    "szal", "szalban", "kontextus", "conversation", "this", "current",
    "our", "here", "the", "an", "and", "in", "of", "to", "is", "was",
    "do", "you", "remember", "recall", "about", "gesprach", "verlauf",
}

_VALUE_CONNECTORS = {
    "is", "was", "are", "were", "equals", "equal", "van", "volt",
    "egyenlo", "egyenlo", "jelentese", "jelentese", "a", "az", "the",
}


@dataclass(frozen=True)
class ConversationRecall:
    answer: str = ""
    confidence: str = "none"
    retrieved_item_count: int = 0
    candidate_count: int = 0
    recent_raw_message_count: int = 0
    source_kind: str = ""

    @property
    def is_direct_hit(self):
        return bool(self.answer) and self.confidence == "high"


def is_safe_direct_recall(query, recall, *, constraints=None):
    """Keep the existing language/script guard in front of the fast path."""
    if not isinstance(recall, ConversationRecall) or not recall.is_direct_hit:
        return False
    return validate_response(
        query,
        recall.answer,
        constraints=constraints,
    ).valid


def estimated_tokens(value):
    """Stable local estimate for diagnostics; it is not a tokenizer contract."""
    text = str(value or "")
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _question_anchors(query):
    tokens = canonical_match_text(query).split()
    if not set(tokens).intersection(_QUESTION_MARKERS) and "?" not in str(query):
        return ()
    anchors = [
        token for token in tokens
        if len(token) >= 3 and token not in _NON_FACT_TOKENS
    ]
    # A single generic anchor is too easy to match accidentally.  This is the
    # primary ambiguity gate for the deterministic path.
    return tuple(dict.fromkeys(anchors)) if len(set(anchors)) >= 2 else ()


def _user_lines(messages, indexed_state, summary, *, query):
    lines = []
    seen = set()

    def add(value, source_kind):
        text = " ".join(str(value or "").strip().split())
        if not text or canonical_match_text(text) == canonical_match_text(query):
            return
        # Indexed-memory labels are retrieval metadata, not user facts.  Never
        # turn them into a deterministic answer, even if their words happen to
        # overlap with the question.
        if re.search(
            r"(?i)\b(?:topic|subject|key|scope|relation)\s*=",
            text,
        ):
            return
        if is_secret_memory_candidate(key=text, value=text, subject=text):
            return
        key = canonical_match_text(text)
        if not key or key in seen:
            return
        seen.add(key)
        lines.append((text, source_kind))

    for message in list(messages or []):
        if str(message.get("role") or "").strip().lower() == "user":
            add(message.get("content"), "recent_raw")

    for stored, source_kind in (
        (indexed_state, "indexed_state"),
        (summary, "window_summary"),
    ):
        for line in str(stored or "").splitlines():
            clean = line.strip()
            if clean.casefold().startswith("- user:"):
                add(clean.split(":", 1)[1], source_kind)
    return lines


def _value_after_anchors(text, anchors):
    matches = list(_WORD_RE.finditer(str(text or "")))
    canonical = [canonical_match_text(match.group(0)) for match in matches]
    position = 0
    last = None
    for anchor in anchors:
        try:
            found = canonical.index(anchor, position)
        except ValueError:
            return ""
        position = found + 1
        last = found
    if last is None:
        return ""

    tail = str(text)[matches[last].end():].strip(" \t:-=,;")
    if not tail or "?" in tail or len(tail) > 240:
        return ""

    tail_words = list(_WORD_RE.finditer(tail))
    while tail_words:
        first = canonical_match_text(tail_words[0].group(0))
        if first not in _VALUE_CONNECTORS:
            break
        tail = tail[tail_words[0].end():].strip(" \t:-=,;")
        tail_words = list(_WORD_RE.finditer(tail))
    if not tail or not _WORD_RE.search(tail):
        return ""
    return tail


def resolve_current_conversation_recall(
    query,
    *,
    messages=(),
    indexed_state="",
    summary="",
):
    """Return one direct value only for a high-confidence current-chat hit."""
    anchors = _question_anchors(query)
    raw_user_count = sum(
        1
        for item in list(messages or [])
        if str(item.get("role") or "").strip().lower() == "user"
    )
    if not anchors:
        return ConversationRecall(recent_raw_message_count=raw_user_count)

    evidence = _user_lines(
        messages,
        indexed_state,
        summary,
        query=query,
    )
    candidates = []
    for text, source_kind in evidence:
        value = _value_after_anchors(text, anchors)
        if value:
            candidates.append((value, source_kind))

    unique = {}
    for value, source_kind in candidates:
        unique.setdefault(canonical_match_text(value), (value, source_kind))
    if len(unique) != 1:
        return ConversationRecall(
            retrieved_item_count=len(evidence),
            candidate_count=len(unique),
            recent_raw_message_count=raw_user_count,
        )

    answer, source_kind = next(iter(unique.values()))
    return ConversationRecall(
        answer=answer,
        confidence="high",
        retrieved_item_count=len(evidence),
        candidate_count=1,
        recent_raw_message_count=raw_user_count,
        source_kind=source_kind,
    )
