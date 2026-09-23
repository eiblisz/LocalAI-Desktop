"""Deterministic semantic dimensions for routing and grounding.

The result is deliberately orthogonal to request activity/depth.  It is safe to
use before retrieval because it never guesses entity spellings or facts.
"""

from dataclasses import dataclass
import re

from .semantic_lexicon_hu import (
    FRESHNESS_MARKERS,
    RELATION_MARKERS,
    REQUESTED_FACT_MARKERS,
)
from .text_normalization import canonical_match_text, canonical_request_text


@dataclass(frozen=True)
class QuestionSemantics:
    requested_fact: str = "general"
    relation: str = "general"
    confidence: str = "low"
    premise_check_required: bool = False
    freshness: str = "stable"


def _has_marker(text, marker):
    marker = canonical_match_text(marker)
    return bool(marker) and bool(
        re.search(r"(?<!\w)" + re.escape(marker) + r"(?!\w)", text)
    )


def _first_match(text, entries):
    for category, markers in entries.items():
        if any(_has_marker(text, marker) for marker in markers):
            return category
    return "general"


def analyze_question(value, *, identity=False):
    text = canonical_request_text(value)
    if not text:
        return QuestionSemantics()

    identity_question = bool(
        identity
        or re.match(r"^(?:ki\s+(?:o|az|ez)\b|kicsoda\b)", text)
    )
    requested_fact = "identity" if identity_question else _first_match(
        text,
        REQUESTED_FACT_MARKERS,
    )
    relation = _first_match(text, RELATION_MARKERS)
    if identity_question:
        relation = "identity"
    elif requested_fact == "cause":
        relation = "cause"
    elif relation == "identity":
        specific_relation = _first_match(
            text,
            {
                category: markers
                for category, markers in RELATION_MARKERS.items()
                if category != "identity"
            },
        )
        relation = specific_relation if specific_relation != "general" else relation
    elif requested_fact == "temporal" and relation in {"authorship", "creation"}:
        relation = "authorship_creation"

    high_confidence = requested_fact != "general" or relation != "general"
    premise_relations = {
        "authorship", "authorship_creation", "creation", "founding", "formation",
        "identity", "birth", "death", "release", "publication", "event_date",
    }
    return QuestionSemantics(
        requested_fact=requested_fact,
        relation=relation,
        confidence="high" if high_confidence else "low",
        premise_check_required=relation in premise_relations,
        freshness=_first_match(text, FRESHNESS_MARKERS).replace("general", "stable"),
    )
