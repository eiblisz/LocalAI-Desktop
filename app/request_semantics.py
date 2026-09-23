from dataclasses import dataclass
import re
import unicodedata


TASK_DIRECT_FACT = "direct_fact"
TASK_ENTITY_OVERVIEW = "entity_overview"
TASK_COMPARISON = "comparison"
TASK_DEEP_RESEARCH = "deep_research"
TASK_DISCOVERY = "discovery"
TASK_EXPLANATION = "explanation"
TASK_GENERAL = "general"


@dataclass(frozen=True)
class RequestProfile:
    kind: str
    response_depth: str
    research_breadth: str
    query_budget: int
    source_budget: int
    page_fetch_budget: int
    requested_fact: str = "general"


def _fold(value):
    normalized = unicodedata.normalize(
        "NFKD",
        " ".join(str(value or "").casefold().split()),
    )
    return "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )


def _contains_any(text, markers):
    return any(marker in text for marker in markers)


def identity_lookup_subject(text):
    """Return the named subject of a short ``who is`` question, if explicit.

    This is deliberately conservative. It accepts a proper name or a multi-word
    entity, while keeping pronouns and relation questions such as "Ki a szerző?"
    out of the web lookup path. The returned value is only a search subject; it
    does not make any factual assertion about that entity.
    """
    raw = " ".join(str(text or "").split())
    match = re.match(
        r"^\s*(?:"
        r"ki(?:csoda)?\s+(?:az\s+)?(?:a\s+)?|"
        r"who\s+is\s+(?:an?\s+)?|"
        r"wer\s+ist\s+(?:(?:ein|eine|einen|der|die|das)\s+)?"
        r")(?P<subject>.+?)\s*[?.!]*\s*$",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""

    subject = " ".join(match.group("subject").split())
    tokens = re.findall(r"[^\W_]+", subject, flags=re.UNICODE)
    folded_tokens = {_fold(token) for token in tokens}
    generic_or_contextual = {
        "te", "en", "o", "you", "he", "she", "they", "it",
        "this", "that", "vagy", "szerzo", "author", "autor",
        "baratnoje", "baratja", "ferje", "feleseg", "anyja", "apja",
        "friend", "wife", "husband", "mother", "father",
    }
    if (
        not tokens
        or folded_tokens.intersection(generic_or_contextual)
        or len(" ".join(tokens)) < 3
    ):
        return ""

    # A one-word named entity (for example a stage name) is accepted only
    # when it is visibly name-like. A two-word subject also covers lowercase
    # user input without guessing at a sentence.
    looks_named = any(token[:1].isupper() for token in tokens)
    return subject if looks_named or len(tokens) >= 2 else ""


def is_entity_identity_question(text):
    """Whether a short question explicitly asks to identify a named entity."""
    return bool(identity_lookup_subject(text))


def classify_requested_fact(text):
    """Return the semantic fact requested by a direct lookup, if recognizable.

    This stays deliberately entity-neutral.  It tells retrieval and evidence
    checks what must be supported, without trying to extract or validate a
    particular named entity on the host.
    """
    if is_entity_identity_question(text):
        return "identity"

    folded = _fold(text)
    patterns = (
        ("temporal", (
            r"\bmikor\b", r"\bmelyik evben\b", r"\bwhen\b", r"\bwhat year\b",
            r"\bwann\b", r"\bdate\b", r"\byear\b",
        )),
        ("location", (
            r"\bhol\b", r"\bwhere\b", r"\bwo\b", r"\bhelye\b",
        )),
        ("quantity", (
            r"\bmennyi\b", r"\bhany\b", r"\bhow many\b", r"\bhow much\b",
            r"\bwie viel\b", r"\bwie viele\b", r"\bnumber\b",
        )),
        ("current_value", (
            r"\bmost\b", r"\bjelenlegi\b", r"\baktualis\b", r"\bcurrent\b",
            r"\blatest\b", r"\baktuell\b", r"\bneueste\b",
        )),
        ("version", (
            r"\bverzio\b", r"\bversion\b", r"\bkiadas\b", r"\brelease\b",
        )),
        ("person_relation", (
            r"\bki\b", r"\bwho\b", r"\bwer\b", r"\bszerzo\b", r"\bauthor\b",
        )),
        ("value", (
            r"\bmi\b", r"\bwhat\b", r"\bwas ist\b", r"\bwert\b",
        )),
    )
    for fact_type, fact_patterns in patterns:
        if any(re.search(pattern, folded) for pattern in fact_patterns):
            return fact_type
    return "general"


def classify_request(text):
    """
    Classify the user-requested activity, not the named entity.

    The profile is intentionally entity-agnostic. It distinguishes the shape of
    work requested (direct fact, overview, comparison, deep research, discovery,
    explanation, general) and provides bounded research/answer budgets.
    """
    raw = " ".join(str(text or "").split())
    folded = _fold(raw)

    explicit_concise = _contains_any(
        folded,
        (
            "roviden",
            "rovid valasz",
            "tomoren",
            "concise",
            "briefly",
            "short answer",
            "kurz",
            "knapp",
        ),
    )
    explicit_detailed = _contains_any(
        folded,
        (
            "reszletes",
            "reszletesen",
            "elemezd",
            "elemzes",
            "melyelemzes",
            "atfogo",
            "teljes koru",
            "riport",
            "report",
            "detailed",
            "in detail",
            "deep dive",
            "thorough",
            "comprehensive",
            "analyze",
            "analysis",
            "ausfuhrlich",
            "vollstandig",
            "analyse",
            "bericht",
        ),
    )

    overview_patterns = (
        r"\bmit tudsz\b.+rol\b",
        r"\bmeselj\b.+rol\b",
        r"\bmutasd be\b",
        r"\bfoglald ossze\b.+rol\b",
        r"\bwhat do you know about\b",
        r"\btell me about\b",
        r"\bgive me an overview of\b",
        r"\boverview of\b",
        r"\bwas weisst du uber\b",
        r"\bwas weißt du uber\b",
        r"\berzahl mir uber\b",
        r"\berzahl mir von\b",
        r"\bgib mir einen uberblick uber\b",
    )
    comparison_markers = (
        "hasonlitsd ossze",
        "mi a kulonbseg",
        "kulonbseg kozt",
        "kulonbseg kozott",
        "compare ",
        "comparison",
        "difference between",
        " vs ",
        " versus ",
        "vergleiche",
        "unterschied zwischen",
    )
    discovery_markers = (
        "keress nekem",
        "ajanlj",
        "ajanlas",
        "melyiket vegyem",
        "hol kapok",
        "hol lehet venni",
        "find me",
        "recommend",
        "recommendation",
        "which should i buy",
        "shopping",
        "such mir",
        "empfiehl",
        "welches soll ich kaufen",
    )
    explanation_markers = (
        "magyarazd el",
        "mi az a ",
        "mi az az ",
        "hogyan mukodik",
        "explain ",
        "what is ",
        "how does ",
        "erklar",
        "was ist ",
        "wie funktioniert",
    )
    direct_fact_patterns = (
        r"\bki irta\b",
        r"\bki a szerzo\b",
        r"\bki alkotta\b",
        r"\bki rendezte\b",
        r"\bki alapitotta\b",
        r"\bmikor irta\b",
        r"\bmikor szuletett\b",
        r"\bmikor tortent\b",
        r"\bmikor alakult\b",
        r"\bmikor jott letre\b",
        r"\bmelyik evben\b",
        r"\bmennyi most\b",
        r"\bmennyi az\b",
        r"\bwho wrote\b",
        r"\bwho authored\b",
        r"\bwho created\b",
        r"\bwho founded\b",
        r"\bwhen did\b",
        r"\bwhen was\b",
        r"\bwhen formed\b",
        r"\bwhen was .+ formed\b",
        r"\bwhen was .+ established\b",
        r"\bwhat year\b",
        r"\bwhat is the current\b",
        r"\bwer schrieb\b",
        r"\bwer verfasste\b",
        r"\bwer grundete\b",
        r"\bwann wurde\b",
        r"\bwann schrieb\b",
        r"\bwann entstand\b",
        r"\bwann wurde .+ gegrundet\b",
    )

    # Resolve the requested activity first.  Depth is a separate dimension:
    # "detailed comparison" remains a comparison rather than becoming a
    # generic research request.
    if any(re.search(pattern, folded) for pattern in overview_patterns):
        kind = TASK_ENTITY_OVERVIEW
        depth = "overview"
        breadth = "balanced"
        query_budget = 1
        source_budget = 8
        page_fetch_budget = 2
    elif _contains_any(folded, comparison_markers):
        kind = TASK_COMPARISON
        depth = "standard"
        breadth = "balanced"
        query_budget = 2
        source_budget = 8
        page_fetch_budget = 3
    elif _contains_any(folded, discovery_markers):
        kind = TASK_DISCOVERY
        depth = "standard"
        breadth = "broad"
        query_budget = 3
        source_budget = 10
        page_fetch_budget = 2
    elif any(re.search(pattern, folded) for pattern in direct_fact_patterns):
        kind = TASK_DIRECT_FACT
        depth = "concise"
        breadth = "narrow"
        query_budget = 1
        source_budget = 4
        page_fetch_budget = 2
    elif is_entity_identity_question(raw):
        kind = TASK_DIRECT_FACT
        depth = "concise"
        breadth = "narrow"
        query_budget = 1
        source_budget = 4
        page_fetch_budget = 2
    elif _contains_any(folded, explanation_markers):
        kind = TASK_EXPLANATION
        depth = "standard"
        breadth = "balanced"
        query_budget = 1
        source_budget = 6
        page_fetch_budget = 2
    else:
        kind = TASK_GENERAL
        depth = "standard"
        breadth = "balanced"
        query_budget = 2
        source_budget = 6
        page_fetch_budget = 2

    if explicit_detailed:
        depth = "detailed"
        breadth = "broad" if kind in {TASK_GENERAL, TASK_EXPLANATION} else breadth
        query_budget = max(query_budget, 3 if kind != TASK_DIRECT_FACT else 1)
        source_budget = max(source_budget, 10 if kind != TASK_DIRECT_FACT else 4)
        page_fetch_budget = max(page_fetch_budget, 4 if kind != TASK_DIRECT_FACT else 2)

    if explicit_concise:
        depth = "concise"
        if kind not in {TASK_DISCOVERY, TASK_COMPARISON}:
            query_budget = min(query_budget, 1)
            source_budget = min(source_budget, 5)
            page_fetch_budget = min(page_fetch_budget, 2)

    return RequestProfile(
        kind=kind,
        response_depth=depth,
        research_breadth=breadth,
        query_budget=max(1, min(int(query_budget), 4)),
        source_budget=max(3, min(int(source_budget), 12)),
        page_fetch_budget=max(1, min(int(page_fetch_budget), 6)),
        requested_fact=classify_requested_fact(raw),
    )


def request_profile_instruction(profile):
    if not isinstance(profile, RequestProfile):
        return ""

    common = (
        "REQUEST PROFILE: "
        f"kind={profile.kind}; depth={profile.response_depth}; "
        f"research_breadth={profile.research_breadth}; "
        f"requested_fact={profile.requested_fact}. "
    )

    if profile.kind == TASK_DIRECT_FACT:
        return (
            common
            + "Answer the exact requested fact immediately. Usually use one to three "
            "short sentences. Correct a false premise when the evidence contradicts it, "
            "but separately answer the requested fact only when the evidence supports it."
        )
    if profile.kind == TASK_ENTITY_OVERVIEW:
        return (
            common
            + "Give a substantive overview rather than a single-fact answer. Cover the "
            "entity's identity/background, major development or milestones, notable people, "
            "works/products/events, and significance or current state where the evidence "
            "supports those aspects. Omit categories that do not fit the entity. A useful "
            "overview will normally need several compact paragraphs or bullets."
        )
    if profile.kind == TASK_COMPARISON:
        return (
            common
            + "Cover each compared subject and the important similarities/differences. "
            "Do not collapse the answer to one isolated fact."
        )
    if profile.kind == TASK_DEEP_RESEARCH:
        return (
            common
            + "Provide a thorough, structured answer with the major evidence-backed aspects "
            "needed to satisfy the user's research/analysis request."
        )
    if profile.kind == TASK_DISCOVERY:
        return (
            common
            + "Provide several useful candidates when evidence allows, preserving the user's "
            "hard constraints and enough detail to compare the options."
        )
    if profile.kind == TASK_EXPLANATION:
        return (
            common
            + "Explain the concept clearly with enough context to understand how and why it "
            "works; do not reduce it to a bare definition unless the user requested brevity."
        )
    return (
        common
        + "Answer at normal useful depth. Do not force a one-to-three sentence factual style "
        "unless the request itself is a direct fact lookup or explicitly asks for brevity."
    )
