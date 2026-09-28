"""Shared answer-length and LOCAL/WEB/HYBRID synthesis policy.

The policy is deterministic and intentionally model-neutral.  It keeps the
operator's normal Ollama budget as the baseline while giving explicit long-form
requests enough bounded room to finish naturally.
"""

from dataclasses import dataclass
import re

from .config import OLLAMA_NUM_PREDICT
from .request_semantics import (
    TASK_ANALYSIS,
    TASK_DEEP_RESEARCH,
    TASK_DIRECT_FACT,
    TASK_ENTITY_OVERVIEW,
    TASK_EXPLANATION,
    TASK_GENERAL,
)
from .text_normalization import (
    canonical_match_text,
    canonical_tokens,
    hungarian_token_matches,
)


SYNTHESIS_LOCAL = "LOCAL"
SYNTHESIS_WEB = "WEB"
SYNTHESIS_HYBRID = "HYBRID"

LENGTH_SHORT = "short"
LENGTH_NORMAL = "normal"
LENGTH_LONG = "long"

SAMPLING_DEFAULT = "default"
SAMPLING_FACTUAL_STRICT = "factual_strict"

_LONG_FORM_TARGET = 2048
_SHORT_FORM_TARGET = 512
_FACTUAL_STRICT_TARGET = 384
_FACTUAL_STRICT_TEMPERATURE = 0.0
_FACTUAL_STRICT_SEED = 42


@dataclass(frozen=True)
class GenerationPolicy:
    synthesis_route: str
    response_length: str
    output_budget: int
    web_required: bool
    freshness: str
    sampling_profile: str = SAMPLING_DEFAULT
    temperature: float | None = None
    seed: int | None = None


def _fold(value):
    return canonical_match_text(value)


def _is_paragraph_unit_token(token):
    canonical = canonical_match_text(token)
    return (
        canonical in {"paragraph", "paragraphs", "absatz", "absatze"}
        or hungarian_token_matches(
            canonical,
            "bekezdes",
            profile="format",
        )
    )


def requested_paragraph_range(text):
    """Return an explicit paragraph-count/range request as (low, high).

    Hungarian accents and grammatical suffixes are handled by the shared
    morphology layer instead of a local wildcard regex.
    """
    tokens = canonical_tokens(text)
    if not tokens:
        return None

    for index, token in enumerate(tokens):
        if not token.isdigit() or len(token) > 2:
            continue
        low = int(token)

        # Canonicalization turns dash ranges (8-12 / 8–12) into adjacent
        # numeric tokens. English/German word ranges keep "to"/"bis".
        if index + 2 < len(tokens) and tokens[index + 1].isdigit():
            high = int(tokens[index + 1])
            if _is_paragraph_unit_token(tokens[index + 2]):
                return tuple(sorted((low, high)))

        if (
            index + 3 < len(tokens)
            and tokens[index + 1] in {"to", "bis"}
            and tokens[index + 2].isdigit()
            and _is_paragraph_unit_token(tokens[index + 3])
        ):
            return tuple(sorted((low, int(tokens[index + 2]))))

        if index + 1 < len(tokens) and _is_paragraph_unit_token(tokens[index + 1]):
            return low, low

    return None

def requested_response_length(text, *, profile=None):
    """Classify requested answer length without treating depth as freshness."""
    folded = _fold(text)
    if not folded:
        return LENGTH_NORMAL

    concise_markers = (
        "roviden", "rovid valasz", "tomoren", "concise", "briefly",
        "short answer", "kurz", "knapp",
    )
    if any(marker in folded for marker in concise_markers):
        return LENGTH_SHORT

    long_markers = (
        "hosszu osszefoglalo", "hosszu valasz", "hosszu forma",
        "long form", "long-form", "long summary", "multiple paragraphs",
        "tobb bekezdes", "tobb bekezdesben", "several paragraphs",
        "mehrere absatze", "langer uberblick",
    )
    if any(marker in folded for marker in long_markers):
        return LENGTH_LONG

    paragraph_range = requested_paragraph_range(text)
    if paragraph_range and paragraph_range[1] >= 6:
        return LENGTH_LONG

    if getattr(profile, "kind", "") == TASK_DEEP_RESEARCH:
        return LENGTH_LONG
    return LENGTH_NORMAL


def output_budget_for_response_length(response_length):
    """Return a finite policy budget while respecting an operator baseline."""
    baseline = max(256, int(OLLAMA_NUM_PREDICT or 1024))
    if response_length == LENGTH_SHORT:
        return max(256, min(baseline, _SHORT_FORM_TARGET))
    if response_length == LENGTH_LONG:
        # An explicit operator baseline may already be higher than this target.
        return max(baseline, _LONG_FORM_TARGET)
    return baseline


def _has_explanatory_scope(text, profile):
    if getattr(profile, "kind", "") in {
        TASK_EXPLANATION,
        TASK_ANALYSIS,
        TASK_ENTITY_OVERVIEW,
        TASK_DEEP_RESEARCH,
    }:
        return True
    folded = _fold(text)
    markers = (
        "magyarazd el", "hogyan mukodik", "mutasd be", "foglald ossze",
        "explain", "how does", "overview", "describe", "erklar",
        "wie funktioniert", "beschreibe",
    )
    return (
        getattr(profile, "kind", "") == TASK_GENERAL
        and any(marker in folded for marker in markers)
    )


def _has_web_augmentation_cue(text, profile):
    if str(getattr(profile, "freshness", "stable") or "stable") != "stable":
        return True
    folded = _fold(text)
    markers = (
        "friss pelda", "aktualis pelda", "current example", "latest example",
        "keress friss", "look up current", "frische beispiele",
    )
    return any(marker in folded for marker in markers)


def build_generation_policy(
    text,
    *,
    profile=None,
    use_web=False,
    conversation_local=False,
):
    """Select common synthesis provenance and generation budget.

    ``use_web`` is decided by the existing web intent policy.  This function
    only decides whether that evidence is the whole answer authority (WEB) or
    an augmentation of a stable explanation (HYBRID).
    """
    response_length = requested_response_length(text, profile=profile)
    if conversation_local or not use_web:
        route = SYNTHESIS_LOCAL
    elif _has_explanatory_scope(text, profile) and _has_web_augmentation_cue(
        text, profile
    ):
        route = SYNTHESIS_HYBRID
    else:
        route = SYNTHESIS_WEB
    strict_factual = bool(
        use_web
        and not conversation_local
        and getattr(profile, "kind", "") == TASK_DIRECT_FACT
    )
    output_budget = output_budget_for_response_length(response_length)
    if strict_factual and response_length != LENGTH_LONG:
        output_budget = max(256, min(output_budget, _FACTUAL_STRICT_TARGET))

    return GenerationPolicy(
        synthesis_route=route,
        response_length=response_length,
        output_budget=output_budget,
        web_required=bool(use_web),
        freshness=str(getattr(profile, "freshness", "stable") or "stable"),
        sampling_profile=(
            SAMPLING_FACTUAL_STRICT if strict_factual else SAMPLING_DEFAULT
        ),
        temperature=(
            _FACTUAL_STRICT_TEMPERATURE if strict_factual else None
        ),
        seed=(_FACTUAL_STRICT_SEED if strict_factual else None),
    )
