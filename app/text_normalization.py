"""Shared, lossless-for-display text matching helpers.

The application always keeps the original user text for chat history, display,
prompts and source labels.  These helpers produce a separate canonical form for
matching only, so Hungarian accents are treated as equivalent without deleting
their base letters (``János`` -> ``janos``, never ``jnos``).
"""

import re
import unicodedata


def canonical_match_text(value):
    """Return an accent-insensitive, case-insensitive token matching form."""
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    accent_folded = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.sub(r"[^\w]+", " ", accent_folded, flags=re.UNICODE)
        .replace("_", " ")
        .split()
    )


def canonical_tokens(value):
    """Return canonical word tokens without changing the caller's original text."""
    return tuple(canonical_match_text(value).split())


def canonical_request_text(value):
    """Canonical request form with only small, context-safe abbreviations expanded."""
    text = canonical_match_text(value)
    replacements = {
        "kb": "korulbelul",
        "pl": "peldaul",
        "szted": "szerinted",
        "sztem": "szerintem",
    }
    tokens = [replacements.get(token, token) for token in text.split()]
    return " ".join(tokens)


def canonical_compact(value):
    """Return the canonical form with token separators removed for ID/spec checks."""
    return "".join(canonical_tokens(value))


def canonical_authority_text(value):
    """Canonical text for technical authority matching while preserving versions."""
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    accent_folded = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.sub(r"[^a-z0-9._+-]+", " ", accent_folded).split()
    )


def canonical_equal(left, right):
    return bool(canonical_match_text(left)) and (
        canonical_match_text(left) == canonical_match_text(right)
    )


def canonical_contains(text, candidate):
    """Match a canonical candidate at word boundaries, never by raw substring."""
    needle = canonical_match_text(candidate)
    haystack = canonical_match_text(text)
    return bool(needle) and bool(
        re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack)
    )


# These are grammatical suffixes only.  The helper is intentionally not a
# fuzzy entity resolver: base tokens must match exactly and only one final token
# may carry one known Hungarian case/plural suffix.
_SAFE_HUNGARIAN_SUFFIXES = tuple(sorted({
    "atok", "etek", "otok", "unk",
    "nak", "nek", "ban", "ben", "bol", "tol", "rol", "hoz", "hez",
    "val", "vel", "kent", "kepp", "jat", "jet", "ja", "je",
    "at", "et", "ot", "on", "en", "ig", "ra", "re", "ba", "be",
    "t", "k",
}, key=len, reverse=True))


def is_safe_hungarian_entity_surface(surface, canonical_entity):
    """Whether *surface* is a simple inflected spelling of an allowed entity.

    Examples: ``Toldit``/``Toldi``, ``Pokolgépről``/``Pokolgép`` and
    ``Petőfi Sándort``/``Petőfi Sándor``.  This never accepts substitutions,
    reordered names, or a new extra name token.
    """
    surface_tokens = canonical_tokens(surface)
    entity_tokens = canonical_tokens(canonical_entity)
    if not surface_tokens or len(surface_tokens) != len(entity_tokens):
        return False
    if surface_tokens == entity_tokens:
        return True
    if surface_tokens[:-1] != entity_tokens[:-1]:
        return False

    base = entity_tokens[-1]
    inflected = surface_tokens[-1]
    if len(base) < 3 or not inflected.startswith(base):
        return False
    suffix = inflected[len(base):]
    return suffix in _SAFE_HUNGARIAN_SUFFIXES


def matches_allowed_entity_surface(surface, allowed_entities):
    """Check a literal against explicitly supplied authority/request entities."""
    return any(
        is_safe_hungarian_entity_surface(surface, candidate)
        for candidate in (allowed_entities or ())
    )
