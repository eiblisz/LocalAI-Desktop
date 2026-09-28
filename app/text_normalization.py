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


# Hungarian morphology matching is deliberately conservative. This module does
# not attempt full lemmatization; callers supply a known canonical lemma and a
# bounded suffix profile. That keeps routing/intent matching tolerant of normal
# Hungarian inflection without turning entity or factual matching into fuzzy
# guessing.
_HUNGARIAN_CASE_SUFFIXES = {
    "nak", "nek", "ban", "ben", "ba", "be", "bol", "tol", "rol",
    "hoz", "hez", "nal", "nel", "val", "vel", "kent", "kepp",
    "ert", "ig", "ra", "re", "on", "en", "at", "et", "ot", "t",
}

_HUNGARIAN_NUMBER_POSSESSIVE_SUFFIXES = {
    "k", "ak", "ek", "ok",
    "m", "d", "a", "e", "am", "em", "om", "ad", "ed", "od",
    "ja", "je", "unk", "atok", "etek", "otok", "uk", "juk",
    "ai", "ei", "aim", "eim", "aid", "eid",
    "anak", "enek", "janak", "jenek",
}

_HUNGARIAN_SEMANTIC_CONTINUATIONS = {
    # Number/person continuations that can follow an already meaningful
    # semantic surface, for example "alakult" -> "alakultak".
    "ak", "ek", "ok", "ik", "unk", "tok", "tek",
    "nak", "nek", "ja", "je", "juk", "jak", "jek",
    "am", "em", "om", "ad", "ed", "od",
}

_HUNGARIAN_FORMAT_SUFFIXES = {
    # Format-unit adjectives such as "bekezdéses" are safe only in this
    # profile and must not broaden general semantic/entity matching.
    "s", "as", "es", "os",
}

_HUNGARIAN_COMMAND_SUFFIXES = {
    # Imperative/polite variants of a supplied command lemma, e.g.
    # "keress" -> "keressél", "keressen", "keressetek".
    "el", "en", "ek", "ed", "etek", "unk",
}

_HUNGARIAN_SUFFIX_PROFILES = {
    "entity": _HUNGARIAN_CASE_SUFFIXES | _HUNGARIAN_NUMBER_POSSESSIVE_SUFFIXES,
    "semantic": (
        _HUNGARIAN_CASE_SUFFIXES
        | _HUNGARIAN_NUMBER_POSSESSIVE_SUFFIXES
        | _HUNGARIAN_SEMANTIC_CONTINUATIONS
    ),
    "format": (
        _HUNGARIAN_CASE_SUFFIXES
        | _HUNGARIAN_NUMBER_POSSESSIVE_SUFFIXES
        | _HUNGARIAN_FORMAT_SUFFIXES
    ),
    "command": _HUNGARIAN_COMMAND_SUFFIXES,
}

# Backward-compatible alias used by older entity-surface tests/callers.
_SAFE_HUNGARIAN_SUFFIXES = tuple(sorted(
    _HUNGARIAN_SUFFIX_PROFILES["entity"],
    key=len,
    reverse=True,
))


def hungarian_token_matches(surface, lemma, *, profile="semantic"):
    """Match one token to a known lemma plus one bounded Hungarian suffix.

    Both sides are accent/case normalized first. This is a recognizer, not a
    generic stemmer: the supplied lemma must match exactly at the beginning and
    the entire remainder must be an allowed suffix for the selected profile.
    """
    surface_tokens = canonical_tokens(surface)
    lemma_tokens = canonical_tokens(lemma)
    if len(surface_tokens) != 1 or len(lemma_tokens) != 1:
        return False

    actual = surface_tokens[0]
    base = lemma_tokens[0]
    if actual == base:
        return True
    if not base or not actual.startswith(base):
        return False

    suffixes = _HUNGARIAN_SUFFIX_PROFILES.get(profile)
    if suffixes is None:
        raise ValueError(f"Unknown Hungarian suffix profile: {profile}")
    suffix = actual[len(base):]
    return bool(suffix) and suffix in suffixes


def canonical_contains_inflected(text, candidate, *, profile="semantic"):
    """Match a phrase while allowing bounded inflection on its final token.

    Earlier tokens must match exactly. This supports semantic lexicon phrases
    without accepting arbitrary fuzzy substitutions.
    """
    haystack = canonical_tokens(text)
    needle = canonical_tokens(candidate)
    if not haystack or not needle or len(needle) > len(haystack):
        return False

    width = len(needle)
    for index in range(len(haystack) - width + 1):
        window = haystack[index:index + width]
        if tuple(window[:-1]) != tuple(needle[:-1]):
            continue
        if hungarian_token_matches(
            window[-1],
            needle[-1],
            profile=profile,
        ):
            return True
    return False


def is_safe_hungarian_entity_surface(surface, canonical_entity):
    """Whether surface is a simple inflected spelling of an allowed entity.

    Examples: Toldit/Toldi, Pokolgépről/Pokolgép and
    Petőfi Sándort/Petőfi Sándor. This never accepts substitutions,
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

    return hungarian_token_matches(
        surface_tokens[-1],
        entity_tokens[-1],
        profile="entity",
    )


def matches_allowed_entity_surface(surface, allowed_entities):
    """Check a literal against explicitly supplied authority/request entities."""
    return any(
        is_safe_hungarian_entity_surface(surface, candidate)
        for candidate in (allowed_entities or ())
    )
