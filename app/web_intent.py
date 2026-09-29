import re
from dataclasses import dataclass

from .artifact_service import ArtifactPlanItem, infer_artifact_requests
from .internal_authority import internal_project_authority_reason
from .memory_extractor import is_explicit_memory_request
from .question_semantics import analyze_question
from .request_semantics import is_entity_identity_question
from .text_normalization import (
    canonical_contains_inflected,
    canonical_match_text,
    hungarian_token_matches,
)


ACTION_MEMORY_WRITE = "memory_write"
ACTION_WEB_RESEARCH = "web_research"
ACTION_ARTIFACT = "artifact"
ACTION_CHAT = "chat"


@dataclass(frozen=True)
class ActionStep:
    kind: str
    payload: object | None = None


@dataclass(frozen=True)
class ActionPlan:
    steps: tuple[ActionStep, ...]
    reason: str = ""

    def has(self, kind: str) -> bool:
        return any(step.kind == kind for step in self.steps)

    @property
    def artifact_plans(self) -> tuple[ArtifactPlanItem, ...]:
        for step in self.steps:
            if step.kind == ACTION_ARTIFACT:
                return tuple(step.payload or ())
        return ()


@dataclass(frozen=True)
class PlannedAction:
    prompt: str
    plan: ActionPlan


def _fold(text):
    return canonical_match_text(text)


def _contains_any(text, markers):
    return any(_fold(marker) in text for marker in markers if _fold(marker))


def is_factual_risk_request(text):
    """
    Return True for concrete relation/date questions where a plausible local-model
    completion is risky even when the fact is not current.

    This is entity-agnostic: it detects question/relation structure, not named QA
    examples or hardcoded people/works.
    """
    raw = str(text or "").strip()
    normalized = _fold(raw)
    if not normalized or _looks_non_factual(raw):
        return False

    # A short, explicit identity lookup is a concrete fact request as well.
    # Keep it tied to the shared semantic parser so desktop and Discord take
    # the same bounded path without entity-specific exceptions.
    if is_entity_identity_question(raw):
        return True

    relation_markers = (
        "ki írta",
        "ki irta",
        "ki a szerző",
        "ki a szerzo",
        "ki alkotta",
        "ki rendezte",
        "ki alapította",
        "ki alapitotta",
        "mikor írta",
        "mikor irta",
        "mikor született",
        "mikor szuletett",
        "mikor történt",
        "mikor tortent",
        "mikor alakult",
        "mikor jott letre",
        "mikor adta ki",
        "mikor adtak ki",
        "mikor jelent meg",
        "melyik évben",
        "melyik evben",
        "szerzője",
        "szerzoje",
        "who wrote",
        "who authored",
        "who created",
        "who founded",
        "when did",
        "when was",
        "when formed",
        "when was formed",
        "when was established",
        "what year",
        "wer schrieb",
        "wer verfasste",
        "wer gründete",
        "wer grundete",
        "wann wurde",
        "wann schrieb",
        "wann entstand",
        "wann wurde gegrundet",
    )
    semantic = analyze_question(raw)
    ordinal_release_selection = bool(
        semantic.requested_fact == "selection"
        and semantic.relation in {"release", "publication"}
    )
    if not _contains_any(normalized, relation_markers) and not ordinal_release_selection:
        return False

    # A proper-name/title cue keeps generic educational questions local.
    named_tokens = re.findall(
        r"(?<!\w)[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű0-9_-]{2,}",
        raw,
    )
    quoted_title = bool(re.search(r'["„”«»][^"„”«»]{2,}["„”«»]', raw))
    year_literal = bool(re.search(r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)", raw))

    # Explicit entity-type grammar is authoritative even when the user types
    # the entity in lowercase. Casing must not decide whether a concrete
    # relation question receives factual-risk verification.
    typed_hu_match = re.search(
        r"(?i)\b(?:a|az)\s+[A-Za-z0-9.&'’_-]{2,}"
        r"(?:\s+[A-Za-z0-9.&'’_-]{2,}){0,3}\s+"
        r"(?P<kind>(?:egy[uü]ttes|zenekar)\w*)\b",
        raw,
    )
    typed_hu_entity = False
    if typed_hu_match:
        kind = typed_hu_match.group("kind")
        typed_hu_entity = bool(
            hungarian_token_matches(kind, "egyuttes", profile="entity")
            or hungarian_token_matches(kind, "zenekar", profile="entity")
        )

    typed_entity = bool(
        typed_hu_entity
        or re.search(
            r"(?i)\b[A-Za-z0-9.&'’_-]{2,}"
            r"(?:\s+[A-Za-z0-9.&'’_-]{2,}){0,3}\s+band\b",
            raw,
        )
        or re.search(
            r"(?i)\bwhen\s+did\s+[A-Za-z0-9.&'’_-]{2,}"
            r"(?:\s+[A-Za-z0-9.&'’_-]{2,}){0,3}\s+release\s+"
            r"(?:its|their|the)?\s*(?:first|debut)\s+(?:studio\s+)?album\b",
            raw,
        )
    )
    return bool(named_tokens or quoted_title or year_literal or typed_entity)


def _legacy_looks_like_web_request(text):
    normalized = _fold(text)
    markers = [
        "keress rá",
        "keress ra",
        "keresd meg",
        "keress nekem",
        "nézd meg online",
        "nezd meg online",
        "nézz utána",
        "nezz utana",
        "interneten",
        "az interneten",
        "weben",
        "web-en",
        "online",
        "legfrissebb",
        "legújabb",
        "legujabb",
        "friss hírek",
        "friss hirek",
        "aktuális ár",
        "aktualis ar",
        "most mennyi",
        "mennyi most",
        "look up",
        "search for",
        "search the web",
        "find online",
        "browse the web",
        "latest news",
        "current price",
        "ár alatt",
        "ar alatt",
        "mennyiért",
        "mennyiert",
        "kapható",
        "kaphato",
        "elérhető",
        "elerheto",
        "ajánlat",
        "ajanlat",
        "hol lehet venni",
        "hol kapok",
        "vásárlás",
        "vasarlas",
        "buy",
        "price",
        "under eur",
        "in stock",
        "available now",
    ]
    def contains_marker(marker):
        phrase = _fold(marker)
        if not phrase:
            return False
        return bool(re.search(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            normalized,
            flags=re.IGNORECASE,
        ))

    currency_cue = bool(
        re.search(r"(?<!\w)eur(?!\w)|€", str(text or ""), re.IGNORECASE)
    )
    return (
        any(contains_marker(marker) for marker in markers)
        or currency_cue
        or canonical_contains_inflected(normalized, "keress", profile="command")
        or is_freshness_sensitive_request(text)
        or is_factual_risk_request(text)
    )


def _has_explicit_web_request(text):
    normalized = _fold(text)
    explicit_markers = (
        "keresd meg", "nezd meg online", "nezz utana",
        "interneten", "weben", "online", "look up", "search for",
        "search the web", "find online", "browse the web",
    )
    return (
        canonical_contains_inflected(
            normalized,
            "keress",
            profile="command",
        )
        or any(marker in normalized for marker in explicit_markers)
    )


def web_request_reason(text):
    """Expose the deterministic authority decision behind automatic web use."""
    if _has_explicit_web_request(text):
        return "explicit_web"
    if internal_project_authority_reason(text):
        return "internal_project_authority"
    if is_freshness_sensitive_request(text):
        return "freshness"
    if is_factual_risk_request(text):
        return "factual_risk"
    if _legacy_looks_like_web_request(text):
        return "external_request"
    return "stable_local"


def looks_like_web_request(text):
    return web_request_reason(text) in {
        "explicit_web",
        "freshness",
        "factual_risk",
        "external_request",
    }


def is_freshness_sensitive_request(text):
    """Return True for questions whose factual answer commonly expires."""
    normalized = _fold(text)
    if not normalized:
        return False
    if internal_project_authority_reason(text):
        return False

    explanatory_markers = (
        "magyarázd el",
        "magyarazd el",
        "mi az a ",
        "mi az az ",
        "mi a különbség",
        "mi a kulonbseg",
        "explain ",
        "what is ",
        "what are ",
        "difference between",
        "erkläre ",
        "erklaere ",
        "was ist ",
        "was sind ",
        "unterschied zwischen",
    )
    explicit_recency_markers = (
        "most",
        "jelenlegi",
        "aktuális",
        "aktualis",
        "mostani",
        "friss",
        "legfrissebb",
        "legújabb",
        "legujabb",
        "mai ",
        "latest",
        "current",
        "today",
        "now",
        "aktuell",
        "heute",
        "neueste",
    )
    # A currency-pair quote is intrinsically time-sensitive even when phrased
    # as "What is ...". Keep this narrow so generic definitions such as
    # "What is an exchange rate?" remain local.
    currency_pair_quote = bool(
        re.search(
            r"(?<![a-z])(?:[a-z]{3})\s*(?:/|-|\s)\s*(?:[a-z]{3})(?![a-z])",
            normalized,
            flags=re.IGNORECASE,
        )
        and (
            "exchange rate" in normalized
            or "wechselkurs" in normalized
            or "árfolyam" in normalized
            or "arfolyam" in normalized
        )
    )
    if currency_pair_quote:
        return True

    if _contains_any(normalized, explanatory_markers) and not _contains_any(
        normalized, explicit_recency_markers
    ):
        return False

    markers = (
        "legfrissebb",
        "friss",
        "friss hírek",
        "friss hirek",
        "aktuális",
        "aktualis",
        "jelenlegi",
        "mostani",
        "most mennyi",
        "mennyi most",
        "árfolyam",
        "arfolyam",
        "árfolyama",
        "arfolyama",
        "tőzsdei ár",
        "tozsdei ar",
        "piaci ár",
        "piaci ar",
        "spot price",
        "market price",
        "exchange rate",
        "wechselkurs",
        "mai ",
        "ma ",
        "ezen a héten",
        "ezen a heten",
        "idén",
        "iden",
        "ár",
        "ára",
        "árai",
        "arak",
        "kapható",
        "kaphato",
        "elérhető",
        "elerheto",
        "készleten",
        "keszleten",
        "verzió",
        "verzio",
        "kiadás",
        "kiadas",
        "megjelent",
        "menetrend",
        "nyitva van",
        "időjárás",
        "idojaras",
        "aktuell",
        "neueste",
        "heute",
        "preis",
        "preise",
        "verfügbar",
        "verfugbar",
        "auf lager",
        "version",
        "veröffentlicht",
        "veroffentlicht",
        "fahrplan",
        "geöffnet",
        "geoffnet",
        "wetter",
        "latest",
        "current",
        "today",
        "this week",
        "this month",
        "this year",
        "price",
        "prices",
        "in stock",
        "available now",
        "availability",
        "version",
        "release",
        "released",
        "schedule",
        "open now",
        "weather",
        "live score",
        "breaking news",
    )
    for marker in markers:
        phrase = _fold(marker)
        if not phrase:
            continue
        if re.search(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            normalized,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def is_creative_or_transform_request(text):
    """Return True only when the requested output itself is non-research work.

    A writing verb alone is not enough: "write an essay about 1848" is factual
    exposition and may need evidence, while a poem, fictional story, rewrite,
    translation, message, or code-generation request can remain local unless the
    user explicitly asks for web research.
    """
    normalized = _fold(text)
    if not normalized:
        return False

    transform_markers = (
        "fogalmazd at", "ird at", "forditsd le", "rewrite", "translate",
        "ubersetz", "paraphrase", "roviditsd le", "summarize this",
    )
    if _contains_any(normalized, transform_markers):
        return True

    creative_markers = (
        "verset", "verset irj", "koltemenyt", "meset", "novellat",
        "fikcios", "kitalalt tortenet", "dalszoveget", "viccet",
        "slogent", "emailt", "e mailt", "levelet", "uzenetet",
        "posztot", "kodot", "programot", "scriptet",
        "poem", "fiction", "short story", "song lyrics", "joke",
        "email", "letter", "message", "social post", "write code",
        "gedicht", "geschichte", "witz", "email", "brief", "nachricht",
    )
    generation_verbs = (
        "irj", "irnal", "keszits", "talalj ki",
        "write", "draft", "create", "brainstorm", "schreib", "erstelle",
    )
    has_generation_verb = any(
        re.search(
            rf"(?<!\w){re.escape(_fold(marker))}(?!\w)",
            normalized,
            flags=re.IGNORECASE,
        )
        for marker in generation_verbs
    )
    return bool(
        has_generation_verb
        and _contains_any(normalized, creative_markers)
    )


def _looks_non_factual(text):
    """Backward-compatible name for non-research generation detection."""
    return is_creative_or_transform_request(text)

def answer_requires_web_fallback(user_text, answer):
    """
    Retry a stable local-chat request on grounded web research if the model itself
    explicitly says its knowledge is missing, stale, or not current.
    """
    if _looks_non_factual(user_text):
        return False

    normalized = _fold(answer)
    if not normalized:
        return True

    markers = (
        "nem tudom",
        "nem vagyok biztos",
        "nincs friss információm",
        "nincs friss informaciom",
        "nincs naprakész információm",
        "nincs naprakesz informaciom",
        "nem rendelkezem friss",
        "nem rendelkezem naprakész",
        "nem rendelkezem naprakesz",
        "nem tudok interneten keresni",
        "nem tudok valós időben hozzáférni",
        "nem tudok valos idoben hozzaferni",
        "nincs valós idejű hozzáférésem",
        "nincs valos ideju hozzaferesem",
        "nem férek hozzá az internethez",
        "nem ferek hozza az internethez",
        "tudásom lezárási",
        "tudasom lezarasi",
        "tudásbázisom",
        "tudasbazisom",
        "i don't know",
        "i do not know",
        "i'm not sure",
        "i am not sure",
        "i don't have current",
        "i do not have current",
        "i don't have up-to-date",
        "i do not have up-to-date",
        "i cannot browse",
        "i can't browse",
        "i cannot access the internet",
        "knowledge cutoff",
        "ich weiß es nicht",
        "ich weiss es nicht",
        "ich bin mir nicht sicher",
        "keine aktuellen informationen",
        "keinen zugriff auf das internet",
        "wissensstand",
    )
    return _contains_any(normalized, markers)


def plan_user_action(text, *, force_web=False, disable_web=False):
    """
    Build one interface-neutral plan for memory, web, artifacts and normal chat.

    Artifact requests may be preceded by web research when the requested content
    is explicitly online/current. Stable requests remain local.
    """
    clean = str(text or "").strip()
    if not clean:
        return ActionPlan((ActionStep(ACTION_CHAT),), "empty/default chat")

    if is_explicit_memory_request(clean):
        return ActionPlan(
            (ActionStep(ACTION_MEMORY_WRITE),),
            "explicit memory request",
        )

    artifacts = tuple(infer_artifact_requests(clean))
    # Keep the reason attached to the interface-neutral plan.  Desktop and
    # Discord consume the same plan, so this is also the single source for
    # user-visible diagnostics.  An explicitly selected web mode remains an
    # override; otherwise an internal host/project request stays local even
    # when its wording contains a general recency term such as "current".
    inferred_web_reason = web_request_reason(clean)
    if bool(disable_web):
        web_reason = inferred_web_reason
        needs_web = False
    elif bool(force_web):
        force_web_allowed = (
            inferred_web_reason != "internal_project_authority"
            and (
                not is_creative_or_transform_request(clean)
                or inferred_web_reason == "explicit_web"
            )
        )
        web_reason = "web_on" if force_web_allowed else inferred_web_reason
        needs_web = force_web_allowed
    else:
        web_reason = inferred_web_reason
        needs_web = web_reason in {
            "explicit_web",
            "freshness",
            "factual_risk",
            "external_request",
        }

    steps = []
    if needs_web:
        steps.append(ActionStep(ACTION_WEB_RESEARCH))

    if artifacts:
        steps.append(ActionStep(ACTION_ARTIFACT, artifacts))
        return ActionPlan(
            tuple(steps),
            f"artifact:{web_reason}",
        )

    if needs_web:
        return ActionPlan(
            tuple(steps),
            web_reason,
        )

    return ActionPlan((ActionStep(ACTION_CHAT),), web_reason)


_NUMBERED_TASK_START = re.compile(
    r"(?m)^\s*(?:\d{1,2}[.)]|[-*])\s+"
)


def split_user_action_units(text):
    """
    Split explicit multi-task messages without breaking a single compound workflow.

    Numbered/bulleted requests and a plain list of standalone question lines become
    independent action units. A sentence such as "find the latest release and
    create an HTML report" remains one unit so its web research can feed the
    artifact step.
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    # A user often pastes a short manual test set as one question per line.
    # Treat that as an explicit batch, rather than turning several unrelated
    # lookups into one broad request with a narrow direct-fact deadline. Requiring
    # every non-empty line to be a complete question preserves ordinary wrapped
    # prose and multi-line artifact instructions as a single action.
    plain_lines = [line.strip() for line in raw.splitlines() if line.strip()]

    def standalone_line_task(line):
        candidate = str(line or "").strip()
        if not candidate:
            return False

        # Test/paste batches often carry a trailing Markdown hard-break slash
        # after a complete question. Treat only trailing presentation escapes
        # as ignorable; preserve the original line text for execution.
        semantic = re.sub(r"[\\]+\s*$", "", candidate).strip()
        if semantic.endswith("?"):
            return True

        folded = canonical_match_text(semantic)
        first = folded.split()[0] if folded.split() else ""
        # Conservative command/opening verbs across the supported UI languages.
        # This is intentionally a batch-boundary recognizer, not an intent
        # classifier; individual units are still routed by plan_user_action().
        command_openers = {
            "irj", "ird", "keszits", "keszitsd", "mutasd", "magyarazd",
            "elemezd", "hasonlitsd", "keress", "nezz", "adj", "foglald",
            "jegyezd", "emlekeztess",
            "write", "create", "make", "explain", "analyze", "compare",
            "find", "search", "show", "summarize", "remember",
            "schreib", "erstelle", "erklar", "analysiere", "vergleiche",
            "suche", "zeige", "fass",
        }
        return first in command_openers

    if (
        len(plain_lines) >= 2
        and all(standalone_line_task(line) for line in plain_lines)
    ):
        return [
            re.sub(r"[\\]+\s*$", "", line).strip()
            for line in plain_lines
        ]

    matches = list(_NUMBERED_TASK_START.finditer(raw))
    if len(matches) <= 1:
        return [raw]

    units = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        piece = raw[start:end].strip()
        if piece:
            units.append(piece)

    return units or [raw]


def plan_user_actions(text, *, force_web=False, disable_web=False):
    """
    Produce independent plans for an explicit numbered/bulleted multi-task request.

    This prevents one artifact request from swallowing neighboring chat/web tasks,
    while preserving web->artifact workflows inside each individual task.
    """
    return tuple(
        PlannedAction(
            prompt=unit,
            plan=plan_user_action(
                unit,
                force_web=(
                    force_web(unit)
                    if callable(force_web)
                    else force_web
                ),
                disable_web=(
                    disable_web(unit)
                    if callable(disable_web)
                    else disable_web
                ),
            ),
        )
        for unit in split_user_action_units(text)
        if str(unit).strip()
    )
