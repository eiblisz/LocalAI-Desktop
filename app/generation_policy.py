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
    TASK_ENTITY_OVERVIEW,
    TASK_EXPLANATION,
    TASK_GENERAL,
)
from .text_normalization import canonical_match_text


SYNTHESIS_LOCAL = "LOCAL"
SYNTHESIS_WEB = "WEB"
SYNTHESIS_HYBRID = "HYBRID"

LENGTH_SHORT = "short"
LENGTH_NORMAL = "normal"
LENGTH_LONG = "long"

_LONG_FORM_TARGET = 2048
_SHORT_FORM_TARGET = 512


@dataclass(frozen=True)
class GenerationPolicy:
    synthesis_route: str
    response_length: str
    output_budget: int
    web_required: bool
    freshness: str


def _fold(value):
    return canonical_match_text(value)


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

    paragraph_count = re.search(
        r"(?:legalabb|at least|mindestens)\s*(\d{1,2})\s*"
        r"(?:bekezdes|paragraph|absatz)",
        folded,
    )
    if paragraph_count and int(paragraph_count.group(1)) >= 6:
        return LENGTH_LONG

    paragraph_range = re.search(
        r"\b(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*"
        r"(?:bekezdes|paragraph|absatz)",
        folded,
    )
    if paragraph_range and max(
        int(paragraph_range.group(1)), int(paragraph_range.group(2))
    ) >= 6:
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
    return GenerationPolicy(
        synthesis_route=route,
        response_length=response_length,
        output_budget=output_budget_for_response_length(response_length),
        web_required=bool(use_web),
        freshness=str(getattr(profile, "freshness", "stable") or "stable"),
    )
