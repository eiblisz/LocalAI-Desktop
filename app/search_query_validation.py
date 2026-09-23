from dataclasses import dataclass
import re

from .text_normalization import canonical_match_text

_META_MARKERS = (
    "search query", "search queries", "query should", "create a query",
    "generate a query", "return only", "current user request", "previous user",
    "as an ai", "i cannot", "could you clarify", "please clarify",
    "you should search", "you should use", "the user s request",
    "keresesi lekerdezes", "keresesi kifejezes", "pontosit", "nem tudok",
    "magyarazat", "lekerdezes legyen", "kereseshez hasznald",
)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_STOP_WORDS = frozenset({
    "what", "when", "where", "which", "with", "from", "that", "this",
    "about", "latest", "current", "please", "search", "find", "look",
    "keress", "keresd", "nezd", "meg", "mikor", "milyen", "melyik",
    "mennyi", "hogyan", "miert", "ez", "az", "egy", "van", "volt",
})


def _fold(value):
    return canonical_match_text(value)


def _terms(value):
    return [
        _fold(term)
        for term in re.findall(r"[^\W_]+", str(value or ""), flags=re.UNICODE)
        if len(_fold(term)) >= 2
    ]


def _intent_anchors(intent):
    return {
        term for term in _terms(intent)
        if len(term) >= 4 and term not in _STOP_WORDS
    }


@dataclass(frozen=True)
class QueryValidation:
    query: str
    reason: str = ""

    @property
    def accepted(self):
        return bool(self.query) and not self.reason


def validate_search_query(candidate, resolved_intent):
    clean = " ".join(str(candidate or "").strip().strip("\"'").split())
    clean = re.sub(r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)", "", clean).strip()[:260]
    intent = " ".join(str(resolved_intent or "").split())
    if not _terms(intent):
        return QueryValidation("", "resolved intent has no lexical search term")
    if not clean:
        return QueryValidation("", "empty query")
    query_terms = _terms(clean)
    if not query_terms:
        return QueryValidation("", "query has no lexical search term")
    if len(clean.split()) > 30 or clean.count(".") >= 2:
        return QueryValidation("", "assistant prose")

    folded = _fold(clean)
    if any(marker in folded for marker in _META_MARKERS):
        return QueryValidation("", "meta or query-writing prose")
    if _CJK_RE.search(clean) and not _CJK_RE.search(intent):
        return QueryValidation("", "unexpected script drift")

    anchors = _intent_anchors(intent)
    intent_terms = set(_terms(intent)) - _STOP_WORDS
    shares_intent_term = bool(intent_terms.intersection(query_terms))
    if (
        len(anchors) <= 3
        and anchors
        and not shares_intent_term
        and not any(anchor in " ".join(query_terms) for anchor in anchors)
    ):
        return QueryValidation("", "obviously unrelated to resolved intent")
    return QueryValidation(clean)


def validate_search_queries(candidates, resolved_intent, limit=4):
    accepted = []
    rejected = []
    for candidate in list(candidates or []):
        result = validate_search_query(candidate, resolved_intent)
        if result.accepted:
            if result.query not in accepted:
                accepted.append(result.query)
        else:
            rejected.append(result.reason)
        if len(accepted) >= limit:
            break
    return accepted, rejected
