"""Deterministic relevance policy for runtime memory context.

Persistent and cross-window memory are useful only when the prompt asks about
user-specific state.  This module deliberately makes that decision before a
store query, so a fresh general-knowledge request cannot acquire unrelated
context merely because a stored item happens to share a broad word.
"""

from dataclasses import dataclass

from .text_normalization import canonical_match_text


def _semantic_tokens(value):
    return {
        token
        for token in canonical_match_text(value).split()
        if len(token) >= 3 or token in {"my", "our", "en"}
    }


def is_memory_architecture_topic_request(user_text):
    """Return True when memory terms are being discussed as product/system features.

    Feature mentions such as "Global Memory", "cross-window retrieval" and the
    "Remember" button must not be interpreted as an instruction to retrieve or
    write personal memory. Keep this semantic and language-agnostic enough for
    architecture/explanation prompts while leaving explicit recall/write queries
    to the normal memory-scope rules.
    """
    normalized = canonical_match_text(user_text)
    tokens = set(normalized.split())
    if not normalized:
        return False

    memory_feature_terms = (
        "window memory",
        "global memory",
        "cross window",
        "cross-window",
        "remember icon",
        "remember button",
        "remember ikon",
        "memoriaarchitekt",
        "memory architecture",
        "memory system",
        "memory routing",
    )
    architecture_terms = {
        "architektura", "architekturaja", "architecture", "routing",
        "retrieval", "persistence", "ikon", "icon", "button", "feature",
        "mukodik", "works", "viselkedes", "behavior",
    }
    explanation_stems = (
        "irj", "magyaraz", "osszegz", "explain", "describe", "summar",
        "how", "hogyan",
    )
    explicit_recall_phrases = (
        "mit jegyeztel meg", "mire emlekszel", "what do you remember",
        "recall from", "emlekezz arra", "jegyezd meg", "remember that",
        "mi van a global memory", "what is in global memory",
        "masik beszelgetes", "other conversation",
    )

    if any(phrase in normalized for phrase in explicit_recall_phrases):
        return False

    has_feature_phrase = any(
        phrase.replace("-", " ") in normalized.replace("-", " ")
        for phrase in memory_feature_terms
    )
    has_architecture_term = bool(tokens & architecture_terms)
    has_explanation_intent = any(
        token.startswith(stem)
        for token in tokens
        for stem in explanation_stems
    )
    return bool(
        (has_feature_phrase or ("memory" in tokens and has_architecture_term))
        and has_explanation_intent
    )


def is_other_window_request(user_text):
    tokens = _semantic_tokens(user_text)
    scope_terms = {
        "beszelgetes", "beszelgetesben", "beszelgetesnek",
        "chat", "chatben", "szal", "szalban",
        "conversation", "thread", "gesprach", "verlauf",
    }
    other_terms = {
        "masik", "masikban", "other", "another", "anderen", "anderer",
    }
    return bool(tokens & scope_terms and tokens & other_terms)


def is_global_memory_request(user_text):
    if is_memory_architecture_topic_request(user_text):
        return False
    sequence = canonical_match_text(user_text).split()
    tokens = set(sequence)
    has_memory_term = any(
        token.startswith(("memoria", "memory", "gedachtnis"))
        for token in tokens
    )
    durable_terms = {
        "globalis", "globalisan", "tartos", "global", "globally",
        "durable", "langzeit", "dauerhaft",
    }
    pairs = set(zip(sequence, sequence[1:]))
    return bool(
        has_memory_term
        and (
            tokens & durable_terms
            or pairs.intersection({("long", "term"), ("hosszu", "tavu")})
        )
    )


_PERSONAL_STATE_TOKENS = {
    "nevem", "lanyom", "fiam", "parom", "ferjem", "felesegem",
    "anyam", "apam", "testverem", "csaladom", "projektem", "projektunk",
    "modellem", "modellunk", "beallitasom", "beallitasunk", "kedvencem",
    "profilom", "adatim", "cimem", "my", "mine", "our", "ours",
}

_RECALL_STEMS = (
    "emleksz", "felidez", "korabb", "eloz", "mondtam", "megadtam",
    "kozoltem", "remember", "recall", "previous", "earlier", "told",
    "provided", "gave", "gesagt", "genannt",
)

_STRONG_CONTEXT_REFERENCE_TOKENS = {
    "elozo", "korabbi", "folytasd", "folytatas", "tovabb", "fenti",
    "previous", "above", "continue", "continuation", "earlier",
}
_WEAK_CONTEXT_REFERENCE_TOKENS = {
    "ez", "ezt", "ennek", "ebben", "erre", "arra", "errol", "arrol",
    "ezzel", "azzal", "azt", "azok",
    "this", "that", "these", "those", "it", "they", "also",
}
_CONTEXT_REFERENT_TOKENS = {
    "beszelgetes", "chat", "szal", "kontextus", "valasz", "uzenet",
    "kerdes", "mondat", "bekezdes", "szoveg", "tema", "terv", "kod",
    "kep", "fajl", "dokumentum", "conversation", "thread", "context",
    "answer", "response", "message", "question", "sentence", "paragraph",
    "text", "topic", "plan", "code", "image", "file", "document",
}
_CONTEXT_ACTION_STEMS = (
    "javit", "fordit", "folytat", "ertekel", "elemez", "magyaraz",
    "bovit", "rovidit", "fogalmaz", "rewrite", "translate", "continue",
    "evaluate", "analy", "explain", "expand", "shorten",
)

def _has_recall_cue(tokens, *, user_text=""):
    if user_text and is_memory_architecture_topic_request(user_text):
        return False
    return any(
        token.startswith(stem)
        for token in tokens
        for stem in _RECALL_STEMS
    )


def is_durable_memory_query(user_text):
    """Require a user-state reference before durable semantic retrieval.

    The memory store performs the second, semantic-overlap check.  A shared
    domain, named product, model family, or number is deliberately insufficient
    here: durable context is for the user's state, preferences, history, or
    project rather than for generic knowledge about the same topic.
    """
    if is_global_memory_request(user_text):
        return True
    tokens = _semantic_tokens(user_text)
    return bool(tokens & _PERSONAL_STATE_TOKENS)


def _has_current_context_reference(user_text):
    if is_memory_architecture_topic_request(user_text):
        return False
    sequence = canonical_match_text(user_text).split()
    tokens = set(sequence)
    if _has_recall_cue(tokens, user_text=user_text):
        return True
    if tokens & _STRONG_CONTEXT_REFERENCE_TOKENS:
        return True

    weak_reference = bool(tokens & _WEAK_CONTEXT_REFERENCE_TOKENS)
    if not weak_reference:
        return False
    if tokens & _CONTEXT_REFERENT_TOKENS:
        return True
    if any(
        token.startswith(stem)
        for token in tokens
        for stem in _CONTEXT_ACTION_STEMS
    ):
        return True

    # A short deictic follow-up such as "Mit gondolsz erről?" can rely on the
    # previous turn.  In a longer standalone request, ordinary Hungarian
    # pronouns such as "arra" or "ezt" must not pull unrelated chat history.
    return len(sequence) <= 10


@dataclass(frozen=True)
class MemoryContextScope:
    memory_scope: str
    include_current_memory: bool
    include_cross_window: bool
    include_global_memory: bool
    cross_window_requested: bool
    global_memory_requested: bool
    reason: str = "fresh_general"


def resolve_memory_context_scope(user_text, *, conversation_local=False):
    """Choose narrowly scoped memory inputs for one model request.

    Current-window direct recall is decided earlier and is intentionally not
    changed here.  This only controls model-context assembly.
    """
    other_window_requested = is_other_window_request(user_text)
    global_memory_requested = is_global_memory_request(user_text)
    durable_relevant = is_durable_memory_query(user_text)
    current_relevant = bool(conversation_local) or _has_current_context_reference(
        user_text
    )
    cross_window_relevant = bool(
        _has_recall_cue(_semantic_tokens(user_text), user_text=user_text)
        and durable_relevant
    )

    include_global_memory = bool(
        not conversation_local
        and not other_window_requested
        and (global_memory_requested or durable_relevant)
    )
    include_cross_window = bool(
        not conversation_local
        and (other_window_requested or cross_window_relevant)
    )
    include_current_memory = bool(
        not other_window_requested
        and not global_memory_requested
        and current_relevant
    )

    if other_window_requested:
        memory_scope = "other_window"
        reason = "explicit_other_conversation"
    elif global_memory_requested:
        memory_scope = "global_memory"
        reason = "explicit_global_memory"
    elif conversation_local:
        memory_scope = "current_window"
        reason = "current_window_context"
    elif include_global_memory or include_cross_window:
        memory_scope = "relevant_memory"
        reason = (
            "durable_user_state"
            if include_global_memory
            else "cross_window_recall"
        )
    elif include_current_memory:
        memory_scope = "current_context"
        reason = "current_context_reference"
    else:
        memory_scope = "fresh_general"
        reason = "fresh_general"

    return MemoryContextScope(
        memory_scope=memory_scope,
        include_current_memory=include_current_memory,
        include_cross_window=include_cross_window,
        include_global_memory=include_global_memory,
        cross_window_requested=other_window_requested,
        global_memory_requested=global_memory_requested,
        reason=reason,
    )
