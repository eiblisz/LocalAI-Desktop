import re
from collections import Counter

from .text_normalization import canonical_match_text


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

_STRONG_HUNGARIAN_CHARS = set("őű")

_GERMAN_WORDS = {
    "der", "die", "das", "und", "oder", "mit", "fuer", "für", "ist", "sind",
    "preis", "preise", "kaufen", "suche", "suchen", "guenstig", "günstig",
    "angebot", "angebote", "keine", "einer", "eine", "einen", "hier",
}

_ENGLISH_WORDS = {
    "the", "and", "or", "with", "is", "are", "was", "were", "be", "been",
    "in", "of", "to", "from", "by", "on", "as", "this", "that", "it", "one",
    "formed", "founded", "known", "group", "band", "price", "prices", "buy",
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
    "ami", "amikor", "annak", "arra", "azt", "ezt", "ehhez", "ennek", "ennek",
    "illetve", "is", "jelentos", "jelentős", "kerdes", "kérdés", "magyarorszag",
    "magyarország", "meg", "mellett", "mint", "nagy", "pedig", "soran", "során",
    "szama", "száma", "szerepe", "szinten", "szintén", "tobb", "több",
}

_VALIDATION_EXCLUDED_RE = re.compile(
    r"https?://\S+"
    r"|`[^`\n]+`"
    r"|\[[^\]\n]+\]\([^)\n]+\)"
    r"|\"[^\"\n]+\""
    r"|“[^”\n]+”"
    r"|„[^”\n]+”"
    r"|»[^«\n]+«"
    r"|‘[^’\n]+’",
    flags=re.UNICODE,
)
_SOURCE_METADATA_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:forrás(?:ok)?|source(?:s)?|quelle(?:n)?|"
    r"hivatkozás(?:ok)?|weboldal(?:cím)?)\s*:",
    flags=re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+", flags=re.IGNORECASE)
_FACTUAL_LITERAL_RE = re.compile(
    r"(?<![\w])(?:[$€£]\s*)?\d(?:[\d.,:/%+-]|\s(?=\d))*"
    r"(?:\s*(?:EUR|USD|HUF|GBP|Ft|%))?(?![\w])",
    flags=re.IGNORECASE,
)

# These are interface-level terms rather than a typo list.  They are allowed
# to remain English in otherwise Hungarian prose and must survive an editorial
# repair unchanged.
_HUNGARIAN_ALLOWED_TECHNICAL_TERMS = {
    "LLM",
    "GPU",
    "Python",
    "token",
    "context window",
    "training",
    "inference",
    "tool use",
}
_CORRUPTED_UNICODE_RE = re.compile(r"[\ufffd\u0000-\u0008\u000b\u000c\u000e-\u001f]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")
_ENGLISH_ADVERB_PARTICIPLE_RE = re.compile(
    r"\b[a-z]{5,}ly\s+[a-z]{4,}(?:ed|ing)\b",
    flags=re.IGNORECASE,
)
_ENGLISH_FUNCTION_WORDS = {
    "the", "and", "or", "with", "from", "is", "are", "was", "were",
    "be", "been", "in", "of", "to", "by", "on", "as", "this", "that",
    "it", "one", "because", "while", "where", "when", "which", "who",
    "called",
}
_ENGLISH_STRONG_GRAMMAR_WORDS = {
    "the", "this", "that", "because", "while", "where", "when", "which",
    "who", "called",
}
_QUALITY_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)", flags=re.UNICODE)
_MAX_QUALITY_EVIDENCE = 8
_CAPITALIZED_LITERAL_RE = re.compile(
    r"\b(?:[A-ZÁÉÍÓÖŐÚÜŰ]{2,}[A-ZÁÉÍÓÖŐÚÜŰ0-9:_./-]*|"
    r"[A-ZÁÉÍÓÖŐÚÜŰ][\w-]*[A-ZÁÉÍÓÖŐÚÜŰ][\w-]*)\b",
    flags=re.UNICODE,
)
_PROPER_NAME_PHRASE_RE = re.compile(
    r"\b(?:[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:[-'][A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű]+)?)"
    r"(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+(?:[-'][A-ZÁÉÍÓÖŐÚÜŰa-záéíóöőúüű]+)?){1,3}\b",
    flags=re.UNICODE,
)

PREFERRED_RESPONSE_LANGUAGE = "hu"

_EXPLICIT_LANGUAGE_MARKERS = {
    "hu": (
        "kizarolag magyarul", "csak magyarul", "magyarul valaszolj",
        "valaszolj magyarul",
    ),
    "en": (
        "respond only in english", "answer only in english", "answer in english",
        "angolul valaszolj", "valaszolj angolul",
    ),
    "de": (
        "nur auf deutsch", "antworte nur auf deutsch", "auf deutsch antworten",
        "nemetul valaszolj", "valaszolj nemetul",
    ),
}


def _fold(value):
    return canonical_match_text(value)


def detect_user_language(text):
    raw = str(text or "").strip()
    if not raw:
        return "unknown"

    lowered = raw.casefold()
    folded_tokens = set(canonical_match_text(raw).split())

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

    if any(token in folded_tokens for token in {
        "who", "what", "how", "when", "where", "which", "why",
        "remember", "search",
    }):
        return "en"

    return "unknown"


def explicit_response_language(text):
    """Return a language explicitly requested in the current turn, if any."""
    folded = canonical_match_text(text)
    for language, markers in _EXPLICIT_LANGUAGE_MARKERS.items():
        if any(canonical_match_text(marker) in folded for marker in markers):
            return language
    return ""


def effective_response_language(text, default=PREFERRED_RESPONSE_LANGUAGE):
    """Resolve a response language without leaving short/ambiguous turns unset."""
    explicit = explicit_response_language(text)
    if explicit:
        return explicit
    detected = detect_user_language(text)
    if detected in {"hu", "de", "en"}:
        return detected
    return str(default or PREFERRED_RESPONSE_LANGUAGE)


def response_language_repair_instruction(text):
    language = effective_response_language(text)
    if language == "hu":
        return (
            "Rewrite the supplied answer in Hungarian. "
            "Correct accidental foreign-language fragments, corrupted Unicode and malformed hybrid words. "
            "Preserve the original paragraph structure and approximately the same length. "
            "Keep legitimate English technical terms such as LLM, token, context window, training, inference, tool use, GPU and Python. "
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
    language = effective_response_language(text)
    if language == "hu":
        return (
            "VÁLASZ NYELVE: Kizárólag magyarul válaszolj az elejétől a végéig. "
            "RESPONSE LANGUAGE: Hungarian only. Answer in Hungarian. "
            "Do not switch to English unless the user explicitly asks for English."
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
        "VÁLASZ NYELVE: Alapértelmezetten kizárólag magyarul válaszolj. "
        "RESPONSE LANGUAGE: Hungarian only unless the user explicitly asks for another language."
    )



def _response_language_scores(text):
    raw = response_validation_text(text)
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
    if any(char in lowered for char in set("áéíóőúű")):
        scores["hu"] += 2
    return scores


def response_validation_text(text):
    """Return prose that is relevant to language/script validation."""
    lines = [
        line for line in str(text or "").splitlines()
        if not _SOURCE_METADATA_LINE_RE.match(line)
    ]
    return _VALIDATION_EXCLUDED_RE.sub(" ", "\n".join(lines))


def protected_factual_literals(text):
    """Extract exact literals a language-only repair must not alter or drop."""
    raw = str(text or "")
    literals = []
    for value in _URL_RE.findall(raw):
        value = value.rstrip(".,;:!?")
        for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
            while value.endswith(closing) and value.count(opening) < value.count(closing):
                value = value[:-1]
        literals.append("url:" + value)
    without_urls = _URL_RE.sub(" ", raw)
    for value in _FACTUAL_LITERAL_RE.findall(without_urls):
        groups = re.findall(r"\d+", value)
        unit_match = re.search(r"(?:EUR|USD|HUF|GBP|Ft|%)", value, re.IGNORECASE)
        unit = unit_match.group(0).upper() if unit_match else ""
        literals.append("number:" + "|".join(groups) + "|" + unit)
    return Counter(literals)


def repair_preserves_factual_literals(original, repaired):
    required = protected_factual_literals(original)
    actual = protected_factual_literals(repaired)
    return all(actual[value] >= count for value, count in required.items())


def _bounded_quality_evidence(value, limit=220):
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit - 3].rstrip() + "..."


def _foreign_language_fragments(prose):
    """Return high-confidence, bounded English prose fragments only.

    English-looking suffixes are deliberately insufficient on their own:
    technical Hungarian prose commonly contains words such as ``embedding``
    and ``learning``.  A fragment needs grammatical/contextual English
    evidence, not just an ASCII morphology match.
    """
    findings = []
    for sentence_match in _QUALITY_SENTENCE_RE.finditer(str(prose or "")):
        sentence = sentence_match.group(0)
        compact = _bounded_quality_evidence(sentence)
        if not compact:
            continue

        for match in _ENGLISH_ADVERB_PARTICIPLE_RE.finditer(sentence):
            findings.append(_bounded_quality_evidence(match.group(0)))

        tokens = [match.group(0).casefold() for match in _ASCII_WORD_RE.finditer(sentence)]
        function_positions = [
            index for index, token in enumerate(tokens)
            if token in _ENGLISH_FUNCTION_WORDS
        ]
        function_words = {tokens[index] for index in function_positions}

        for index, token in enumerate(tokens[:-1]):
            if token == "called":
                findings.append("called " + tokens[index + 1])

        has_sentence_grammar = (
            len(function_positions) >= 3
            or (
                len(function_positions) >= 2
                and bool(function_words & _ENGLISH_STRONG_GRAMMAR_WORDS)
            )
        )
        if has_sentence_grammar:
            findings.append(compact)

    return tuple(dict.fromkeys(findings))[:_MAX_QUALITY_EVIDENCE]


def hungarian_output_quality_evidence(text):
    """Return issue-to-bounded-response-span evidence for Hungarian quality checks."""
    prose = response_validation_text(text)
    evidence = {}
    corrupted = _CORRUPTED_UNICODE_RE.search(prose)
    if corrupted:
        evidence["corrupted_unicode"] = (
            _bounded_quality_evidence(prose[max(0, corrupted.start() - 40):corrupted.end() + 40]),
        )
    foreign_fragments = _foreign_language_fragments(prose)
    if foreign_fragments:
        evidence["foreign_language_fragment"] = foreign_fragments
    return evidence


def hungarian_output_quality_issues(text):
    """Return generic editorial-quality issues for Hungarian prose.

    This deliberately avoids a list of individual misspellings.  The
    deterministic checks catch broken Unicode and high-confidence foreign-prose
    context. It intentionally does not treat length as a defect: healthy
    long Hungarian answers must not create another model call.
    """
    return tuple(hungarian_output_quality_evidence(text))


def protected_response_literals(text):
    """Extract technical/proper-name literals that editorial repair may not drop."""
    raw = str(text or "")
    literals = []
    for term in _HUNGARIAN_ALLOWED_TECHNICAL_TERMS:
        if term.casefold() in raw.casefold():
            literals.append("technical:" + term.casefold())
    for value in _CAPITALIZED_LITERAL_RE.findall(response_validation_text(raw)):
        literals.append("name:" + value.rstrip("._-/:"))
    for value in _PROPER_NAME_PHRASE_RE.findall(response_validation_text(raw)):
        literals.append("name:" + value.casefold())
    return Counter(literals)


def repair_preserves_response_shape(original, repaired, *, preserve_proper_names=True):
    """Keep a quality repair editorial: preserve facts, structure and length."""
    source = str(original or "").strip()
    candidate = str(repaired or "").strip()
    if not source or not candidate:
        return False
    if not repair_preserves_factual_literals(source, candidate):
        return False

    if preserve_proper_names:
        required_literals = protected_response_literals(source)
        actual_literals = protected_response_literals(candidate)
        if any(actual_literals[value] < count for value, count in required_literals.items()):
            return False

    source_paragraphs = [item for item in re.split(r"\n\s*\n", source) if item.strip()]
    candidate_paragraphs = [item for item in re.split(r"\n\s*\n", candidate) if item.strip()]
    if len(source_paragraphs) >= 2 and len(candidate_paragraphs) != len(source_paragraphs):
        return False

    source_length = len(re.sub(r"\s+", "", source))
    candidate_length = len(re.sub(r"\s+", "", candidate))
    if source_length >= 600 and not (source_length * 0.85 <= candidate_length <= source_length * 1.15):
        return False
    return True


def response_language_matches(user_text, response_text):
    expected = effective_response_language(user_text)

    scores = _response_language_scores(response_text)
    expected_score = scores.get(expected, 0)
    foreign_scores = [
        score for language, score in scores.items()
        if language != expected
    ]
    strongest_foreign = max(foreign_scores or [0])

    if strongest_foreign < 3:
        return True
    if expected_score == 0:
        return False
    return expected_score + 1 >= strongest_foreign
