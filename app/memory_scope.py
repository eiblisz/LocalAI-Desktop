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

_CONTEXT_REFERENCE_TOKENS = {
    "ez", "ezt", "ennek", "ebben", "erre", "arra", "azt", "azok",
    "elozo", "korabbi", "folytasd", "folytatas", "tovabb",
    "this", "that", "these", "those", "it", "they", "previous",
    "above", "continue", "continuation", "also",
}

def _has_recall_cue(tokens):
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
    tokens = _semantic_tokens(user_text)
    return bool(tokens & _CONTEXT_REFERENCE_TOKENS or _has_recall_cue(tokens))


@dataclass(frozen=True)
class MemoryContextScope:
    memory_scope: str
    include_current_memory: bool
    include_cross_window: bool
    include_global_memory: bool
    cross_window_requested: bool
    global_memory_requested: bool


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
        _has_recall_cue(_semantic_tokens(user_text)) and durable_relevant
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
    elif global_memory_requested:
        memory_scope = "global_memory"
    elif conversation_local:
        memory_scope = "current_window"
    elif include_global_memory or include_cross_window:
        memory_scope = "relevant_memory"
    elif include_current_memory:
        memory_scope = "current_context"
    else:
        memory_scope = "fresh_general"

    return MemoryContextScope(
        memory_scope=memory_scope,
        include_current_memory=include_current_memory,
        include_cross_window=include_cross_window,
        include_global_memory=include_global_memory,
        cross_window_requested=other_window_requested,
        global_memory_requested=global_memory_requested,
    )
