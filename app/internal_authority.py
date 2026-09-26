"""Model-neutral authority classification for the host's own project/system.

The user can ask about the application that is serving the conversation.  Such
requests are not public-web questions merely because they use words like
``current`` or ``latest``.  This module deliberately uses the configured host
identity plus general project/system language; it does not special-case a
particular product name or model family.
"""

from .config import APP_NAME
from .text_normalization import canonical_compact, canonical_match_text


_INTERNAL_FEATURE_STEMS = (
    "architektur", "memoria", "memory", "routing", "route", "retrieval",
    "persistence", "runtime", "beallitas", "setting", "configur",
    "kontextus", "context", "beszelget", "conversation", "chat",
    "elozmeny", "history", "remember", "modellvalt", "model switch",
    "integral", "workflow", "orchestrat", "interface", "felulet",
)

_PROJECT_SUBJECT_TOKENS = {
    "projektem", "projektunk", "project", "app", "application",
    "alkalmazas", "rendszerem", "rendszerunk", "system", "rendszer",
}

_SELF_REFERENCE_TOKENS = {
    "sajat", "sajatom", "sajatunk", "ez", "ezen", "ennek", "ebben",
    "this", "our", "my", "current",
}

_EXTERNAL_CURRENT_TERMS = {
    "legfrissebb", "legujabb", "latest", "newest", "release", "released",
    "verzio", "version", "ara", "arak", "price", "prices", "weather",
    "idojaras", "news", "hirek", "market", "stock", "availability",
    "elerheto", "available", "schedule", "menetrend",
}

_RECENCY_TOKENS = {
    "most", "jelenlegi", "aktualis", "friss", "legfrissebb", "legujabb",
    "latest", "current", "today", "now", "newest",
}


def _configured_host_identity_present(text):
    """Match the configured application identity without relying on spelling gaps."""
    host_identity = canonical_compact(APP_NAME)
    prompt_identity = canonical_compact(text)
    return bool(
        host_identity
        and len(host_identity) >= 5
        and host_identity in prompt_identity
    )


def _has_external_current_requirement(tokens):
    return bool(tokens & _RECENCY_TOKENS and tokens & _EXTERNAL_CURRENT_TERMS)


def internal_project_authority_reason(text):
    """Return a stable internal-authority reason, or ``""`` when not applicable.

    A configured host identity can establish that the application itself is the
    subject.  A deictic/possessive project reference also works for a user's
    current project.  In both cases a system-level feature is required, which
    prevents broad domain overlap (for example, a generic question about local
    AI) from being treated as internal state.
    """
    normalized = canonical_match_text(text)
    tokens = set(normalized.split())
    if not tokens or _has_external_current_requirement(tokens):
        return ""

    has_feature = any(
        token.startswith(stem)
        for token in tokens
        for stem in _INTERNAL_FEATURE_STEMS
    )
    if not has_feature:
        return ""

    if _configured_host_identity_present(text):
        return "host_internal_system"

    has_project_subject = bool(tokens & _PROJECT_SUBJECT_TOKENS)
    has_self_reference = bool(tokens & _SELF_REFERENCE_TOKENS)
    if has_project_subject and has_self_reference:
        return "user_project_system"
    return ""


def is_internal_project_authority_request(text):
    return bool(internal_project_authority_reason(text))
