import re
import unicodedata


_HUNGARIAN_WORDS = {
    "a",
    "az",
    "es",
    "én",
    "en",
    "ki",
    "mi",
    "nekem",
    "te",
    "hogy",
    "jegyezd",
    "emlekezz",
    "emlékezz",
    "nevem",
    "neved",
    "lanyom",
    "lányom",
    "fiam",
    "parom",
    "párom",
    "baratnoje",
    "barátnője",
    "baratja",
    "barátja",
    "fia",
    "lanya",
    "lánya",
    "keress",
    "nezd",
    "nézd",
    "mennyi",
    "milyen",
    "alatt",
    "kaphato",
    "kapható",
}

_STRONG_HUNGARIAN_CHARS = set("őű")


def _fold(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def detect_user_language(text):
    raw = str(text or "").strip()
    if not raw:
        return "unknown"

    lowered = raw.casefold()
    tokens = re.findall(r"[\wÀ-ž]+", lowered, flags=re.UNICODE)
    folded_tokens = {_fold(token) for token in tokens}

    if any(char in lowered for char in _STRONG_HUNGARIAN_CHARS):
        return "hu"

    marker_hits = 0
    for marker in _HUNGARIAN_WORDS:
        if _fold(marker) in folded_tokens:
            marker_hits += 1

    if marker_hits >= 1 and any(
        _fold(token) in folded_tokens
        for token in ("ki", "mi", "nekem", "hogy", "jegyezd", "keress", "nezd")
    ):
        return "hu"

    if any(token in folded_tokens for token in {"who", "what", "how", "remember", "search"}):
        return "en"

    return "unknown"


def response_language_instruction(text):
    language = detect_user_language(text)
    if language == "hu":
        return (
            "RESPONSE LANGUAGE: The current user message is Hungarian. "
            "Answer in Hungarian. Do not switch to English unless the user explicitly asks for English."
        )
    if language == "en":
        return (
            "RESPONSE LANGUAGE: The current user message is English. "
            "Answer in English unless the user explicitly asks for another language."
        )
    return (
        "RESPONSE LANGUAGE: Answer in the same language as the current user message. "
        "Do not switch languages without an explicit user request."
    )
