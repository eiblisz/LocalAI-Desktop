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
    "mikor",
    "miert",
    "miért",
    "hogyan",
    "melyik",
    "mennyi",
    "hol",
    "mit",
    "irta",
    "írta",
    "irt",
    "írt",
    "alatt",
    "kaphato",
    "kapható",
    "valaszolj",
    "válaszolj",
    "magyarul",
    "irj",
    "írj",
    "keszits",
    "készíts",
    "rovid",
    "rövid",
    "reszletes",
    "részletes",
    "osszefoglalot",
    "összefoglalót",
    "elemezd",
    "hasonlitsd",
    "hasonlítsd",
}

_STRONG_HUNGARIAN_CHARS = set("áéíóőúű")

_GERMAN_WORDS = {
    "der", "die", "das", "und", "oder", "mit", "fuer", "für", "ist", "sind",
    "preis", "preise", "kaufen", "suche", "suchen", "guenstig", "günstig",
    "angebot", "angebote", "keine", "einer", "eine", "einen", "hier",
}

_ENGLISH_WORDS = {
    "the", "and", "or", "with", "is", "are", "price", "prices", "buy",
    "search", "find", "verified", "product", "products", "source", "sources",
}

_HUNGARIAN_RESPONSE_WORDS = {
    "a", "az", "es", "és", "egy", "vagy", "van", "volt", "lett", "vannak",
    "amely", "aki", "hogy", "nem", "csak", "olyan", "azonban", "majd", "mar",
    "már", "ota", "óta", "szerint", "kozott", "között", "elott", "előtt",
    "utan", "után", "evben", "évben", "alakult", "irta", "írta", "jelent",
    "jelent meg", "magyar", "zenekar", "mu", "mű", "cimu", "című",
    "arat", "árat", "arak", "árak", "termek", "termék", "termekek", "termékek",
    "forras", "forrás", "forrasok", "források", "talalat", "találat",
    "talalatok", "találatok", "ellenorzott", "ellenőrzött", "tudtam", "lehetett",
}


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
        for token in (
            "ki",
            "mi",
            "nekem",
            "hogy",
            "jegyezd",
            "keress",
            "nezd",
            "mikor",
            "miert",
            "hogyan",
            "melyik",
            "mennyi",
            "hol",
            "mit",
            "irta",
            "irt",
            "valaszolj",
            "magyarul",
            "irj",
            "keszits",
            "elemezd",
            "hasonlitsd",
        )
    ):
        return "hu"

    german_hits = sum(
        1 for token in folded_tokens
        if token in {_fold(value) for value in _GERMAN_WORDS}
    )
    if german_hits >= 2:
        return "de"

    if any(token in folded_tokens for token in {"who", "what", "how", "remember", "search"}):
        return "en"

    return "unknown"


def response_language_repair_instruction(text):
    language = detect_user_language(text)
    if language == "hu":
        return (
            "Írd át az alábbi választ kizárólag magyar nyelvre. "
            "A tényeket, számokat, URL-eket, termékneveket és tulajdonneveket "
            "pontosan őrizd meg. A személynevek írásmódját és szórendjét ne változtasd meg. "
            "Ne adj hozzá és ne vegyél el információt. Csak a magyarra átírt választ add vissza."
        )
    if language == "de":
        return (
            "Schreibe die folgende Antwort ausschließlich auf Deutsch um. "
            "Bewahre Fakten, Zahlen, URLs, Produktnamen und Eigennamen exakt. "
            "Ändere weder Schreibweise noch Reihenfolge von Personennamen. "
            "Füge keine Informationen hinzu und entferne keine. "
            "Gib nur die deutsch umgeschriebene Antwort zurück."
        )
    if language == "en":
        return (
            "Rewrite the following answer in English only. Preserve every fact, "
            "number, URL, product name and proper name exactly. Do not add or remove "
            "information. Return only the English answer."
        )
    return (
        "Rewrite the supplied answer in the same language as the current user message. "
        "Preserve all facts, numbers, URLs and proper names exactly. Return only the answer."
    )


def response_language_instruction(text):
    language = detect_user_language(text)
    if language == "hu":
        return (
            "VÁLASZ NYELVE: Kizárólag magyarul válaszolj az elejétől a végéig. "
            "RESPONSE LANGUAGE: Hungarian only. Do not switch to English unless "
            "the user explicitly asks for English."
        )
    if language == "en":
        return (
            "RESPONSE LANGUAGE: The current user message is English. "
            "Answer in English unless the user explicitly asks for another language."
        )
    if language == "de":
        return (
            "ANTWORTSPRACHE: Antworte ausschließlich auf Deutsch. "
            "RESPONSE LANGUAGE: German only unless the user explicitly asks "
            "for another language."
        )
    return (
        "RESPONSE LANGUAGE: Answer in the same language as the current user message. "
        "Do not switch languages without an explicit user request."
    )



def _response_language_scores(text):
    raw = str(text or "")
    lowered = raw.casefold()
    tokens = re.findall(r"[\wÀ-ž]+", lowered, flags=re.UNICODE)
    folded_tokens = [_fold(token) for token in tokens]

    hu_values = {_fold(value) for value in _HUNGARIAN_RESPONSE_WORDS}
    de_values = {_fold(value) for value in _GERMAN_WORDS}
    en_values = {_fold(value) for value in _ENGLISH_WORDS}

    scores = {
        "hu": sum(1 for token in folded_tokens if token in hu_values),
        "de": sum(1 for token in folded_tokens if token in de_values),
        "en": sum(1 for token in folded_tokens if token in en_values),
    }
    if any(char in lowered for char in _STRONG_HUNGARIAN_CHARS):
        scores["hu"] += 2
    return scores


def response_language_matches(user_text, response_text):
    expected = detect_user_language(user_text)
    if expected not in {"hu", "de", "en"}:
        return True

    scores = _response_language_scores(response_text)
    expected_score = scores.get(expected, 0)
    foreign_scores = [
        score for language, score in scores.items()
        if language != expected
    ]
    strongest_foreign = max(foreign_scores or [0])

    if strongest_foreign < 2:
        return True
    return expected_score >= strongest_foreign
