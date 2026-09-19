import re
from dataclasses import dataclass

from .artifact_service import ArtifactPlanItem, infer_artifact_requests
from .memory_extractor import is_explicit_memory_request


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


def _fold(text):
    return " ".join(str(text or "").casefold().split())


def looks_like_web_request(text):
    normalized = " ".join(str(text or "").lower().split())
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
        "friss hírek",
        "friss hirek",
        "aktuális ár",
        "aktualis ar",
        "most mennyi",
        "look up",
        "search for",
        "search the web",
        "find online",
        "browse the web",
        "latest news",
        "current price",
        "eur",
        "€",
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
        "under €",
        "under eur",
        "in stock",
        "available now",
    ]
    return (
        any(marker in normalized for marker in markers)
        or bool(re.search(r"\bkeress\w*\b", normalized, flags=re.IGNORECASE))
    )


def is_freshness_sensitive_request(text):
    """Return True for questions whose factual answer commonly expires."""
    normalized = _fold(text)
    if not normalized:
        return False

    markers = (
        "legfrissebb",
        "friss hírek",
        "friss hirek",
        "aktuális",
        "aktualis",
        "jelenlegi",
        "mostani",
        "most mennyi",
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
    return any(marker in normalized for marker in markers)


def _looks_non_factual(text):
    normalized = _fold(text)
    markers = (
        "írj egy",
        "irj egy",
        "fogalmazd át",
        "fogalmazd at",
        "fordítsd le",
        "forditsd le",
        "találj ki",
        "talalj ki",
        "verset",
        "viccet",
        "történetet",
        "tortenetet",
        "write a",
        "rewrite",
        "translate",
        "brainstorm",
        "poem",
        "story",
        "joke",
        "schreib",
        "übersetz",
        "ubersetz",
    )
    return any(marker in normalized for marker in markers)


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
    return any(marker in normalized for marker in markers)


def plan_user_action(text, *, force_web=False):
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
    needs_web = (
        bool(force_web)
        or looks_like_web_request(clean)
        or is_freshness_sensitive_request(clean)
    )

    steps = []
    if needs_web:
        steps.append(ActionStep(ACTION_WEB_RESEARCH))

    if artifacts:
        steps.append(ActionStep(ACTION_ARTIFACT, artifacts))
        return ActionPlan(
            tuple(steps),
            "artifact request with web grounding"
            if needs_web
            else "artifact request",
        )

    if needs_web:
        return ActionPlan(
            tuple(steps),
            "explicit or freshness-sensitive web request",
        )

    return ActionPlan((ActionStep(ACTION_CHAT),), "stable local chat")
