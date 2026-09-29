"""Small deterministic helpers for the direct-fact fast path.

The helpers deliberately make no claim about a specific person, work, band, or
other entity.  Their role is limited to shaping an already-classified lookup and
checking whether its evidence includes the kind of fact the user asked for.
"""

import re

from .question_semantics import analyze_question
from .request_semantics import identity_lookup_subject
from .text_normalization import canonical_match_text, hungarian_token_matches


def _clean(value):
    return " ".join(str(value or "").split())


def _fold(value):
    return canonical_match_text(_clean(value))


def _hungarian_object_search_surface(value):
    """Return a conservative search-only lemma for a Hungarian object surface.

    This is used only after the grammar has already identified the object of
    "mikor írta <subject> a/az <object>?". It never changes the user-visible
    text or factual authority. The goal is to avoid sending an attached
    accusative suffix into web search (for example "Toldit" -> "Toldi" or
    "Silver Storyt" -> "Silver Story").
    """
    text = _clean(value)
    if not text:
        return text
    parts = text.split()
    token = parts[-1]
    folded = _fold(token)

    # Generic object nouns are not title candidates and are handled elsewhere.
    # For title-like objects, prefer the smallest safe accusative removal.
    replacement = token
    if len(token) >= 4 and folded.endswith(("at", "et", "ot", "öt")):
        stem = token[:-2]
        # Only remove a linking vowel suffix when the resulting stem remains a
        # plausible word surface. This covers forms such as "Hamletet".
        if len(stem) >= 3:
            replacement = stem
    elif len(token) >= 3 and folded.endswith("t"):
        replacement = token[:-1]

    if replacement and replacement != token:
        parts[-1] = replacement
        return " ".join(parts)
    return text


def _marked_title(prompt):
    """Extract a title explicitly marked by quotes or title wording, if present."""
    raw = _clean(prompt)
    quoted = re.search(r"[\"'“”„](.{2,120}?)[\"'“”„]", raw)
    if quoted:
        return _clean(quoted.group(1))

    patterns = (
        r"(?:\ba\s+|\baz\s+)(.+?)\s+(?:c[ií]m[űu]|c\.)\s+(?:vers(?:et)?|m[űu](?:vet)?|konyv(?:et)?|regeny(?:t)?)\b",
        r"(?:\bthe\s+)?(.+?)\s+(?:titled|called)\s+(?:work|book|poem|novel)\b",
        r"(.+?)\s+(?:mit dem titel|namens)\s+",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = _clean(match.group(1))
            # Limit to the last title-like clause.  This removes a preceding
            # question word or alleged person without relying on their identity.
            candidate = re.split(
                r"\b(?:[ií]rta|wrote|authored|created|schrieb)\b",
                candidate,
                flags=re.IGNORECASE,
            )[-1].strip()
            # In "Mikor írta a Szerző az Ének c. verset?" the first
            # article starts the alleged author clause.  The final article is
            # the explicitly marked work title; taking it is a structural
            # parse, not a general typo/name correction.
            article_parts = re.split(
                r"\s+(?:a|az)\s+",
                candidate,
                flags=re.IGNORECASE,
            )
            if len(article_parts) > 1:
                candidate = article_parts[-1].strip()
            if 2 <= len(candidate) <= 120:
                return candidate

    # Natural Hungarian direct-fact questions often omit "című", for example
    # "Mikor írta <person> a <Work>?"  Keep the alleged person out of search
    # authority by extracting only the post-article object when it is visibly
    # title-like.  We intentionally keep Hungarian inflection intact instead of
    # guessing a lemma; search providers can normalize it, while the host avoids
    # inventing entity spelling.
    implicit = re.match(
        r"^\s*mikor\s+[ií]rta\s+(.+?)\s+(?:a|az)\s+(.+?)\s*[?!.]*$",
        raw,
        flags=re.IGNORECASE,
    )
    if implicit:
        alleged_subject = _clean(implicit.group(1))
        candidate = _clean(implicit.group(2)).rstrip("?!.").strip()
        subject_tokens = re.findall(r"[^\W_]+", alleged_subject, flags=re.UNICODE)
        generic_objects = {
            "verset", "muvet", "konyvet", "regenyt", "dalt", "tortenetet",
        }
        if (
            2 <= len(candidate) <= 120
            and candidate[:1].isupper()
            and any(token[:1].isupper() for token in subject_tokens)
            and _fold(candidate) not in generic_objects
        ):
            return _hungarian_object_search_surface(candidate)
    return ""


def _release_subject_surface(prompt):
    """Extract the named entity in a first/debut-release question when structural."""
    raw = _clean(prompt)
    patterns = (
        r"(?i)\b(?:mi|melyik)\s+volt\s+(?:a|az)\s+"
        r"(?P<subject>.+?)\s+(?:els[őo]\w*|deb[uü]t\w*)\s+"
        r"(?:album\w*|nagylemez\w*|lemez\w*)\s+(?:a\s+)?"
        r"(?:c[ií]m\w*|neve)\b",
        r"(?i)\b(?:what|which)\s+was\s+(?P<subject>.+?)(?:'s|\s+)"
        r"(?:first|debut)\s+(?:studio\s+)?album(?:'s)?\s+(?:title|name)\b",
        r"(?i)\bmikor\s+(?:adta|adtak|kiadta|kiadtak)\s+(?:ki\s+)?"
        r"(?:a|az)\s+(?:els[őo]|deb[uü]t\w*)\s+[^?]{0,40}?\s+"
        r"(?:a|az)\s+(?P<subject>.+?)\s+(?:egy[uü]ttes|zenekar)\b",
        r"(?i)\bmikor\s+jelent\s+meg\s+(?:a|az)\s+"
        r"(?P<subject>.+?)\s+(?:egy[uü]ttes|zenekar)\s+"
        r"(?:els[őo]|deb[uü]t\w*)\s+(?:albuma|nagylemeze|lemeze)\b",
        r"(?i)\bwhen\s+did\s+(?P<subject>.+?)\s+release\s+"
        r"(?:its|their|the)?\s*(?:first|debut)\s+(?:studio\s+)?album\b",
        r"(?i)\bwann\s+ver[oö]ffentlichte\s+(?P<subject>.+?)\s+"
        r"(?:sein|ihr|das)?\s*(?:erste|erstes|deb[uü]t)\w*\s+album\b",
        # Generic typed-entity fallback for ordinal/debut questions such as
        # "melyik nagylemez volt az első a sampleband zenekarnak?". The
        # surrounding release/debut checks decide whether this surface is used.
        r"(?i)\b(?:a|az)\s+(?P<subject>[A-Za-z0-9.&'’_-]{2,}"
        r"(?:\s+[A-Za-z0-9.&'’_-]{2,}){0,4})\s+"
        r"(?P<entity_type>(?:egy[uü]ttes|zenekar)\w*)\b",
        r"(?i)\b(?P<subject>[A-Za-z0-9.&'’_-]{2,}"
        r"(?:\s+[A-Za-z0-9.&'’_-]{2,}){0,4})\s+band\b",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            entity_type = match.groupdict().get("entity_type")
            if entity_type:
                if (
                    not hungarian_token_matches(
                        entity_type,
                        "egyuttes",
                        profile="entity",
                    )
                    and not hungarian_token_matches(
                        entity_type,
                        "zenekar",
                        profile="entity",
                    )
                ):
                    continue
            subject = _clean(match.group("subject")).strip(" .?!,;:")
            if 2 <= len(subject) <= 120:
                return subject
    return ""


def _debut_release_surface_supported(text):
    """Recognize first/debut-album wording without requiring adjacent words."""
    folded = _fold(text)
    debut_markers = (
        "elso album", "elso nagylemez", "elso lemez",
        "debut album", "debut studio album", "debutalo album",
        "debutlemez", "debutalbum", "first album", "first studio album",
        "erstes album",
    )
    if any(marker in folded for marker in debut_markers):
        return True

    # Model/evidence paraphrases may insert a short modifier phrase between
    # "first/debut" and the album noun, for example:
    # "elso sajat nevet viselo albuma" or "first self titled studio album".
    # Keep the window deliberately small so unrelated earlier "first" mentions
    # do not satisfy the requested debut-release relation.
    patterns = (
        r"\b(?:elso|debutalo)\b(?:\s+\w+){0,4}\s+"
        r"(?:album\w*|nagylemez\w*|lemez\w*)\b",
        r"\b(?:first|debut)\b(?:\s+\w+){0,4}\s+"
        r"(?:album\w*|record\w*)\b",
        r"\b(?:album\w*|nagylemez\w*|lemez\w*)\b"
        r"(?:\s+\w+){0,3}\s+(?:elso|debutalo)\b",
        r"\b(?:album\w*|record\w*)\b(?:\s+\w+){0,3}\s+first\b",
        r"\b(?:erste|erstes|debut\w*)\b(?:\s+\w+){0,4}\s+album\w*\b",
    )
    return any(re.search(pattern, folded) for pattern in patterns)


def _is_debut_release_request(prompt):
    return _debut_release_surface_supported(prompt)


def _single_edit_or_exact(left, right):
    left = re.sub(r"[^a-z0-9]", "", _fold(left))
    right = re.sub(r"[^a-z0-9]", "", _fold(right))
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 6 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    short_index = 0
    edits = 0
    for char in long:
        if short_index < len(short) and char == short[short_index]:
            short_index += 1
        else:
            edits += 1
            if edits > 1:
                return False
    return True


def _subject_supported_in_text(text, subject):
    folded_text = _fold(text)
    folded_subject = _fold(subject)
    if not folded_subject:
        return False
    if re.search(r"(?<!\w)" + re.escape(folded_subject) + r"(?!\w)", folded_text):
        return True

    subject_tokens = folded_subject.split()
    if len(subject_tokens) == 1 and len(subject_tokens[0]) >= 6:
        for token in re.findall(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű0-9]+", str(text or "")):
            if _single_edit_or_exact(subject_tokens[0], token):
                return True

    # Entity names may be written with or without punctuation/spaces
    # (for example WASP/W.A.S.P.). Match the same alphanumeric surface
    # conservatively across separators without depending on user casing.
    raw_subject = re.sub(r"[^A-Za-z0-9]", "", str(subject or ""))
    if 2 <= len(raw_subject) <= 32 and re.fullmatch(r"[A-Za-z0-9]+", raw_subject):
        compact_pattern = r"(?i)(?<![A-Za-z0-9])" + r"[^A-Za-z0-9]*".join(
            re.escape(ch) for ch in raw_subject
        ) + r"(?![A-Za-z0-9])"
        return bool(re.search(compact_pattern, str(text or "")))
    return False


def _debut_release_item_supported(text, request_text):
    if not _is_debut_release_request(request_text):
        return True
    subject = _release_subject_surface(request_text)
    if subject and not _subject_supported_in_text(text, subject):
        return False
    return _debut_release_surface_supported(text)


def direct_fact_title_surface(prompt):
    """Return a structurally identified work/title surface from the request."""
    return _marked_title(prompt)


def requested_fact_relation(prompt):
    """Classify the relation behind a requested fact without extracting entities."""
    semantic_relation = analyze_question(prompt).relation
    if semantic_relation == "event_date":
        return "event"
    if semantic_relation in {
        "authorship", "authorship_creation", "creation", "formation", "birth",
        "release", "publication",
    }:
        if semantic_relation in {"authorship", "authorship_creation"}:
            return "creation"
        if semantic_relation in {"release", "publication"}:
            return "release"
        return semantic_relation

    folded = _fold(prompt)
    relation_patterns = (
        ("creation", (
            r"\b(?:irta|megirta|keletkezett|keszult)\b",
            r"\b(?:wrote|written|authored|composed|created)\b",
            r"\b(?:schrieb|verfasste|entstand)\b",
        )),
        ("formation", (
            r"\b(?:alakult|megalakult|letrejott)\b",
            r"\b(?:formed|founded|established)\b",
            r"\b(?:gegrundet|entstand)\b",
        )),
        ("birth", (
            r"\b(?:szuletett|born|geboren)\b",
        )),
        ("release", (
            r"\b(?:megjelent|jelent meg|kiadta|kiadtak|adta ki|adtak ki|kiadas|kiadva)\b",
            r"\b(?:released|published|publication)\b",
            r"\b(?:erschien|veroffentlicht|ausgabe)\b",
        )),
        ("event", (
            r"\b(?:tortent|happened|occurred|geschah)\b",
        )),
    )
    for relation, patterns in relation_patterns:
        if any(re.search(pattern, folded) for pattern in patterns):
            return relation
    return "general"


def derive_premise_neutral_query(prompt, requested_fact="general"):
    """Return a conservative host-side direct-fact query and a strategy label.

    A neutral query is only used when the target is explicitly delimited.  For
    free-form questions, returning the validated original request is safer than
    guessing an entity boundary.
    """
    clean = _clean(prompt)
    identity_subject = identity_lookup_subject(clean)
    if identity_subject:
        return identity_subject, "identity_lookup_subject"

    relation = requested_fact_relation(clean)
    release_subject = _release_subject_surface(clean)
    if (
        relation == "release"
        and release_subject
        and _is_debut_release_request(clean)
    ):
        if str(requested_fact or "") == "temporal":
            query = f"{release_subject} debut first album release date year"
        elif str(requested_fact or "") == "selection":
            query = f"{release_subject} debut first album discography"
        else:
            query = ""
        if query:
            return (
                query,
                "premise_neutral_entity_release_relation",
            )

    title = _marked_title(clean)
    if not title:
        return clean, "validated_original"

    hungarian_creation_query = bool(
        re.search(r"\b(?:mikor|irta|irja|cimu|verset|muvet)\b", _fold(clean))
    )
    temporal_suffixes = {
        "creation": (
            "szerző keletkezés megírás éve"
            if hungarian_creation_query
            else "literary work author composition writing date year"
        ),
        "formation": "formation founding date year",
        "birth": "birth date year",
        "release": "release publication date year",
        "event": "event date year",
        "general": "date year",
    }
    suffixes = {
        "temporal": temporal_suffixes[relation],
        "location": "location place where",
        "quantity": "number quantity",
        "current_value": "current latest value",
        "version": "latest version release",
        "person_relation": "author creator founder",
        "value": "fact information",
    }
    suffix = suffixes.get(str(requested_fact or "general"), "fact information")
    return f"{title} {suffix}", "premise_neutral_title_relation"


def targeted_fact_refinement_query(prompt, requested_fact="general"):
    """Derive one stricter, bounded follow-up query after insufficient evidence."""
    clean = _clean(prompt)
    requested_fact = str(requested_fact or "")
    if requested_fact not in {"temporal", "selection"}:
        return ""

    relation = requested_fact_relation(clean)
    release_subject = _release_subject_surface(clean)
    if (
        relation == "release"
        and release_subject
        and _is_debut_release_request(clean)
    ):
        if requested_fact == "selection":
            return f"{release_subject} debut first album discography"
        return f"{release_subject} debut studio album release year"

    if requested_fact != "temporal":
        return ""

    title = _marked_title(clean)
    if not title:
        return ""

    hungarian_creation_query = bool(
        re.search(r"\b(?:mikor|irta|irja|cimu|verset|muvet)\b", _fold(clean))
    )
    suffixes = {
        "creation": (
            "szerző eredeti keletkezés éve"
            if hungarian_creation_query
            else "literary work author original composition year"
        ),
        "formation": "formation year",
        "birth": "birth year",
        "release": "release year",
        "event": "event date",
        "general": "date year",
    }
    return f"{title} {suffixes[requested_fact_relation(clean)]}"


def _evidence_text(payload):
    parts = []
    for item in dict(payload or {}).get("results") or []:
        parts.extend((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
    return "\n".join(parts)


def _temporal_relation_supported(text, relation):
    folded = _fold(text)
    markers = {
        "creation": (
            "irta", "megirta", "keletkez", "keszult", "wrote", "written",
            "authored", "composed", "created", "schrieb", "verfasste",
        ),
        "formation": (
            "alakult", "megalakult", "letrejott", "formed", "founded",
            "established", "gegrundet",
        ),
        "birth": ("szuletett", "born", "geboren"),
        "release": (
            "megjelent", "jelent meg", "kiadta", "kiadtak", "adta ki", "adtak ki",
            "kiadas", "kiadva", "released", "published", "publication",
            "erschien", "veroffentlicht", "ausgabe",
        ),
        "event": ("tortent", "happened", "occurred", "geschah"),
    }
    expected = markers.get(relation)
    return True if not expected else any(marker in folded for marker in expected)


_DATE_RE = re.compile(
    r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b"
)

_CREATION_DATE_MARKERS = (
    "irta", "megirta", "keletkez", "keszult", "wrote", "written",
    "authored", "composed", "created", "schrieb", "verfasste",
)

_PUBLICATION_DATE_MARKERS = (
    "jelent meg", "megjelent", "kiadas", "kiadva", "publikal",
    "adta ki", "adtak ki", "kiadta", "kiadtak", "kiadott",
    "published", "publication", "edition", "released",
    "erschien", "veroffentlicht", "ausgabe",
)


def _nearest_marker_distance(text, pivot_start, pivot_end, markers):
    best = None
    for marker in markers:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            marker_end = index + len(marker)
            if marker_end <= pivot_start:
                distance = pivot_start - marker_end
            elif index >= pivot_end:
                distance = index - pivot_end
            else:
                distance = 0
            if best is None or distance < best:
                best = distance
            start = index + 1
    return best


def _creation_date_supported(text):
    """Require a date to bind to creation rather than publication.

    Search snippets often place a publication year beside an authorship note.
    Evaluate each punctuation-bounded clause independently first; this prevents
    "published in 1847, written for the competition" from promoting 1847 to a
    composition year while still accepting "wrote it in 1912".
    """
    raw = str(text or "")
    clauses = [
        _fold(clause)
        for clause in re.split(r"[.!?;,]+", raw)
        if clause.strip()
    ]
    for clause in clauses:
        for match in _DATE_RE.finditer(clause):
            creation_distance = _nearest_marker_distance(
                clause,
                match.start(),
                match.end(),
                _CREATION_DATE_MARKERS,
            )
            publication_distance = _nearest_marker_distance(
                clause,
                match.start(),
                match.end(),
                _PUBLICATION_DATE_MARKERS,
            )
            if creation_distance is None:
                continue
            if (
                publication_distance is not None
                and publication_distance < creation_distance
            ):
                continue
            if creation_distance <= 80:
                return True
    return False


def answer_contains_temporal_literal(text):
    """Return whether user-visible text contains an explicit date/year literal."""
    return bool(_DATE_RE.search(str(text or "")))


def requested_fact_supported(payload, requested_fact="general", request_text=""):
    """Whether provider snippets/page text contain a usable fact-shaped signal."""
    text = _evidence_text(payload)
    if not _clean(text):
        return False

    requested_fact = str(requested_fact or "general")

    if (
        requested_fact == "selection"
        and requested_fact_relation(request_text) == "release"
        and _is_debut_release_request(request_text)
    ):
        for item in dict(payload or {}).get("results") or []:
            item_text = "\n".join((
                str(item.get("title") or ""),
                str(item.get("snippet") or ""),
                str(item.get("page_text") or ""),
                str(item.get("pre_extracted_context") or ""),
            ))
            if _debut_release_item_supported(item_text, request_text):
                return True
        return False

    checks = {
        "temporal": r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        "quantity": r"\b\d+(?:[.,]\d+)?\b",
        "version": r"(?i)\bv?\d+(?:\.\d+){1,3}\b|\b(?:version|release|verzi[oó]|kiad[aá]s)\b",
        "current_value": r"\b\d+(?:[.,]\d+)?\b",
        "location": r"(?i)\b(?:in|at|from|located|helye|itt|ban|ben)\b",
        "person_relation": r"(?i)\b(?:wrote|written|author|creator|founded|founded by|[ií]rta|szerz[őo]|alkotta|alap[ií]totta)\b",
        "identity": r"(?i)\b(?:is|was|known|musician|artist|actor|writer|band|egy|az|zen[ée]sz|eloado|sz[ií]nész|iro)\b",
    }
    pattern = checks.get(requested_fact)
    if not pattern or not re.search(pattern, text):
        return not pattern

    if requested_fact != "temporal":
        return True

    relation = requested_fact_relation(request_text)
    if relation == "general":
        return True

    # The date and requested relation must occur within the same result. A
    # publication/edition year alone cannot satisfy a creation-date question.
    for item in dict(payload or {}).get("results") or []:
        item_text = "\n".join((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
        if not re.search(pattern, item_text):
            continue
        if relation == "creation":
            if _creation_date_supported(item_text):
                return True
            continue
        if relation == "release" and not _debut_release_item_supported(
            item_text,
            request_text,
        ):
            continue
        if _temporal_relation_supported(item_text, relation):
            return True
    return False


def _named_fact_literals(text):
    values = []

    def add(value):
        literal = _clean(value).strip(" .,:;!?")
        folded = _fold(literal)
        if literal and folded and all(_fold(item) != folded for item in values):
            values.append(literal)

    for match in re.finditer(r'["“”„«»](.{2,120}?)["“”„«»]', str(text or "")):
        add(match.group(1))

    # Also catch unquoted multi-word title/proper-name surfaces such as
    # A Town Called Malice. Single-word unquoted surfaces remain deliberately
    # out of scope because they cannot be separated reliably from ordinary prose.
    for match in re.finditer(
        r"\b[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{1,}"
        r"(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{1,})+\b",
        str(text or ""),
    ):
        add(match.group(0))

    return tuple(values)


def unsupported_release_named_literals(answer, request_text, payload):
    """Return named answer details not bound to the requested release subject.

    Literal presence somewhere in a multi-result evidence bundle is not enough:
    a title from an adjacent entity must not be attached to the entity the user
    asked about. For first/debut-release questions, each detectable named detail
    in the answer must appear in an evidence result that also names the requested
    subject. The user's premise is not treated as factual authority.
    """
    if requested_fact_relation(request_text) != "release":
        return ()
    subject = _release_subject_surface(request_text)
    if not subject:
        return ()

    results = list(dict(payload or {}).get("results") or [])
    unsupported = []

    for literal in _named_fact_literals(answer):
        folded_literal = _fold(literal)
        if not folded_literal:
            continue

        supported = False
        for item in results:
            item_text = "\n".join((
                str(item.get("title") or ""),
                str(item.get("snippet") or ""),
                str(item.get("page_text") or ""),
                str(item.get("pre_extracted_context") or ""),
            ))
            if not _subject_supported_in_text(item_text, subject):
                continue
            if _subject_supported_in_text(item_text, literal):
                supported = True
                break

        if not supported:
            unsupported.append(literal)

    return tuple(sorted(set(unsupported), key=str.casefold))


def answer_temporal_literals_supported_by_evidence(answer, request_text, payload):
    """Require each answer year to bind to the requested relation in evidence."""
    years = tuple(dict.fromkeys(
        re.findall(
            r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)",
            str(answer or ""),
        )
    ))
    if not years:
        return True

    relation = requested_fact_relation(request_text)
    results = list(dict(payload or {}).get("results") or [])
    for year in years:
        supported = False
        for item in results:
            item_text = "\n".join((
                str(item.get("title") or ""),
                str(item.get("snippet") or ""),
                str(item.get("page_text") or ""),
                str(item.get("pre_extracted_context") or ""),
            ))
            if year not in item_text:
                continue
            if relation == "release" and not _debut_release_item_supported(
                item_text,
                request_text,
            ):
                continue

            clauses = [
                clause.strip()
                for clause in re.split(r"[.!?;,\n]+", item_text)
                if clause.strip() and year in clause
            ]
            for clause in clauses:
                if relation == "creation":
                    if _creation_date_supported(clause):
                        supported = True
                        break
                    continue
                if relation == "general" or _temporal_relation_supported(
                    clause,
                    relation,
                ):
                    supported = True
                    break
            if supported:
                break
        if not supported:
            return False
    return True


_NAME_TOKEN_RE = r"[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{1,}"
_NAME_SPAN_RE = rf"{_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE}){{1,2}}"


def _hungarian_alleged_creator(prompt):
    match = re.match(
        r"^\s*mikor\s+[ií]rta\s+(.+?)\s+(?:a|az)\s+",
        _clean(prompt),
        flags=re.IGNORECASE,
    )
    return _clean(match.group(1)) if match else ""


def _creator_surfaces_from_text(text):
    raw = str(text or "")
    candidates = []
    patterns = (
        rf"(?P<person>{_NAME_SPAN_RE})\s+(?i:[ií]rta|meg[ií]rta|wrote|authored|composed|created)\b",
        rf"(?i:\b(?:written|authored|composed|created)\s+by\s+)(?P<person>{_NAME_SPAN_RE})\b",
        rf"(?i:\b(?:szerz[őo]je|szerz[őo]|author)\s*(?::|is|was)?\s*)(?P<person>{_NAME_SPAN_RE})\b",
    )
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, raw):
            person = _clean(match.group("person"))
            folded = _fold(person)
            if folded and folded not in seen:
                seen.add(folded)
                candidates.append(person)
    return candidates


def supported_creator_surfaces(payload):
    candidates = []
    seen = set()
    for item in dict(payload or {}).get("results") or []:
        item_text = "\n".join((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
        for person in _creator_surfaces_from_text(item_text):
            folded = _fold(person)
            if folded and folded not in seen:
                seen.add(folded)
                candidates.append(person)
    return tuple(candidates)


def creation_answer_conflicts_with_evidence(answer, request_text, payload):
    """Detect affirmation of a false creator premise contradicted by evidence."""
    alleged = _hungarian_alleged_creator(request_text)
    if not alleged:
        return False

    # For a creator/date question, an unnegated answer that repeats the
    # user's alleged creator in the creation relation is verification-worthy
    # unless the evidence parser cleanly supports that creator and no competing
    # creator surface. The premise itself is never authority; missing or mixed
    # creator extraction therefore fails toward verification, not acceptance.
    alleged_folded = _fold(alleged)
    creators = supported_creator_surfaces(payload)
    creator_folds = {_fold(person) for person in creators if _fold(person)}
    alleged_uniquely_supported = bool(creator_folds) and (
        creator_folds == {alleged_folded}
    )
    answer_text = str(answer or "")
    for clause in re.split(r"[.!?;,]+", answer_text):
        folded = _fold(clause)
        if not folded or alleged_folded not in folded:
            continue
        if not any(marker in folded for marker in _CREATION_DATE_MARKERS):
            continue
        if re.search(r"\b(?:nem|not|nicht)\b", folded):
            continue
        return not alleged_uniquely_supported
    return False


def _deescape_evidence_surface(value):
    """Remove repeated Markdown escaping from a short evidence display surface."""
    text = str(value or "")
    slash = chr(92)
    for char in "`*_{}[]()#+-.!|>":
        escaped = slash + char
        while escaped in text:
            text = text.replace(escaped, char)
    return text


def _split_answer_sentences(text):
    """Split normal prose without breaking dotted acronyms such as W.A.S.P."""
    value = _clean(text)
    if not value:
        return ()
    parts = re.split(
        r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ0-9\"“„«])",
        value,
    )
    return tuple(part.strip() for part in parts if part.strip())


def render_resolved_direct_fact(fact, requested_fact="general", *, language="hu"):
    """Render the host-resolved core fact without invoking a model."""
    fact = dict(fact or {})
    subject = _deescape_evidence_surface(fact.get("subject")).strip()
    title = _deescape_evidence_surface(fact.get("title")).strip()
    year = str(fact.get("year") or "").strip()
    requested_fact = str(requested_fact or "general")
    if not subject or not title:
        return ""

    if requested_fact == "selection":
        if language == "de":
            answer = f"Das erste Album von {subject} war {title}."
            if year:
                answer += f" Es erschien {year}."
            return answer
        if language == "en":
            answer = f"The first album by {subject} was {title}."
            if year:
                answer += f" It was released in {year}."
            return answer
        answer = f"A {subject} első nagylemeze a {title} című album volt."
        if year:
            answer += f" Az album {year}-ben jelent meg."
        return answer

    if requested_fact == "temporal" and year:
        if language == "de":
            return f"Das Debütalbum von {subject} erschien {year}."
        if language == "en":
            return f"The debut album by {subject} was released in {year}."
        return f"A {subject} debütáló albuma {year}-ben jelent meg."

    return ""


def anchor_resolved_direct_fact_answer(
    draft,
    fact,
    requested_fact="general",
    *,
    language="hu",
):
    """Replace only the model's leading core-fact sentence with host authority.

    Direct-fact prompts require the requested fact in the first sentence. Once
    the host has resolved that core relation deterministically, the model must
    not be allowed to override it. Later sentences are preserved so useful,
    evidence-grounded context can still survive normal factual validation.
    """
    core = render_resolved_direct_fact(
        fact,
        requested_fact,
        language=language,
    )
    if not core:
        return str(draft or "").strip()

    sentences = list(_split_answer_sentences(draft))
    if len(sentences) <= 1:
        return core

    supporting_sentences = []
    for sentence in sentences[1:]:
        # Do not preserve a second model sentence that merely restates the same
        # resolved debut/release relation. Keep genuinely additional context.
        if (
            str(fact.get("relation") or "") == "release"
            and _is_debut_release_request(sentence)
            and requested_fact_relation(sentence) == "release"
        ):
            continue
        supporting_sentences.append(sentence)

    supporting = " ".join(supporting_sentences).strip()
    return (core + (" " + supporting if supporting else "")).strip()


def _subject_display_surface(text, subject):
    """Return the evidence spelling of *subject* when it can be matched safely."""
    raw = _deescape_evidence_surface(text)
    folded_subject = _fold(subject)
    if not folded_subject:
        return ""

    # Normal token-spaced form first.
    canonical_tokens = folded_subject.split()
    if canonical_tokens:
        token_pattern = r"(?i)(?<!\w)" + r"\s+".join(
            re.escape(token) for token in canonical_tokens
        ) + r"(?!\w)"
        match = re.search(token_pattern, raw)
        if match:
            return _clean(match.group(0)).strip(" ,;:")

    subject_tokens = folded_subject.split()
    if len(subject_tokens) == 1 and len(subject_tokens[0]) >= 6:
        for match in re.finditer(
            r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű0-9]{6,}",
            raw,
        ):
            if _single_edit_or_exact(subject_tokens[0], match.group(0)):
                return match.group(0)

    # Punctuated compact forms such as WASP / W.A.S.P.
    raw_subject = re.sub(r"[^A-Za-z0-9]", "", str(subject or ""))
    if 2 <= len(raw_subject) <= 32 and re.fullmatch(r"[A-Za-z0-9]+", raw_subject):
        compact_pattern = (
            r"(?i)(?<![A-Za-z0-9])"
            + r"[^A-Za-z0-9]*".join(re.escape(ch) for ch in raw_subject)
            + r"(?:\.)?(?![A-Za-z0-9])"
        )
        match = re.search(compact_pattern, raw)
        if match:
            surface = match.group(0).strip(" ,;:")
            if surface.endswith(".") and surface.count(".") <= 1:
                surface = surface[:-1]
            return surface
    return ""


def _debut_title_candidates_from_item(item, request_text):
    """Extract conservative debut-album title candidates from one bound result."""
    fields = [
        str(item.get("snippet") or ""),
        str(item.get("page_text") or ""),
        str(item.get("pre_extracted_context") or ""),
        str(item.get("title") or ""),
    ]
    item_text = "\n".join(fields)
    subject = _release_subject_surface(request_text)
    if not subject or not _debut_release_item_supported(item_text, request_text):
        return ()

    subject_surface = _subject_display_surface(item_text, subject) or _clean(subject)
    candidates = []

    def add(value):
        title = _clean(_deescape_evidence_surface(value)).strip(" .,:;!?-–—")
        folded = _fold(title)
        if (
            not title
            or len(title) > 120
            or not folded
            or folded in {
                "discography", "album", "debut album", "first album",
                "debut studio album", "first studio album",
            }
        ):
            return
        if all(_fold(existing) != folded for existing in candidates):
            candidates.append(title)

    folded_item = _fold(item_text)
    self_titled_markers = (
        "self titled", "selftitled", "eponymous",
        "sajat nevet viselo", "sajat cimu", "sajat nevu",
        "selbstbetitelt", "selbstbenannt",
    )
    if any(marker in folded_item for marker in self_titled_markers):
        add(subject_surface)

    # Encyclopedic result shape:
    # "Kill 'Em All is the debut studio album by ... Metallica"
    # or "W.A.S.P. is the debut studio album by ... W.A.S.P."
    title_pattern = re.compile(
        r"(?im)^\s*(?P<title>[^\n]{2,120}?)\s+"
        r"(?:is|was|ist|war)\s+(?:the\s+|das\s+|die\s+)?"
        r"(?:debut|first|erste\w*)\s+(?:studio\s+)?album\b"
    )
    for field in fields[:3]:
        for match in title_pattern.finditer(field):
            add(match.group("title"))

    # Band/artist overview pages often summarize the first releases as
    # "first two studio albums, Title A (1984) and Title B (1985)". The first
    # listed title is structurally bound to the requested ordinal relation.
    first_list_pattern = re.compile(
        r"(?i)\bfirst\b(?:\s+[\w-]+){0,4}\s+albums?\s*[,/:;-]\s*"
        r"(?P<title>[^,;()]{2,100}?)\s*\((?:19|20)\d{2}\)"
    )
    for field in fields[:3]:
        for match in first_list_pattern.finditer(field):
            add(match.group("title"))

    # Result-title fallback is intentionally narrow: only an explicit album
    # page title may supply the value. A band/artist biography title must never
    # be mistaken for the requested album.
    result_title = _clean(item.get("title"))
    body = "\n".join(fields[:3])
    if (
        result_title
        and _debut_release_item_supported(body, request_text)
        and re.search(
            r"(?i)\((?:album|studio album|debut album)\)",
            result_title,
        )
    ):
        cleaned_title = re.sub(
            r"\s*[-|:]\s*(?:wikipedia|discogs|allmusic|musicbrainz).*$",
            "",
            result_title,
            flags=re.IGNORECASE,
        )
        cleaned_title = re.sub(
            r"\s*\((?:album|studio album|debut album)\)\s*$",
            "",
            cleaned_title,
            flags=re.IGNORECASE,
        )
        add(cleaned_title)

    return tuple(candidates)


def _release_year_candidates_from_item(item, request_text):
    fields = [
        str(item.get("snippet") or ""),
        str(item.get("page_text") or ""),
        str(item.get("pre_extracted_context") or ""),
    ]
    years = []
    first_list_year_pattern = re.compile(
        r"(?i)\bfirst\b(?:\s+[\w-]+){0,4}\s+albums?\s*[,/:;-]\s*"
        r"[^,;()]{2,100}?\s*\((?P<year>(?:19|20)\d{2})\)"
    )
    for field in fields:
        for match in first_list_year_pattern.finditer(field):
            year = match.group("year")
            if year not in years:
                years.append(year)

        # Work at result-field scope rather than splitting on periods: dotted
        # entity names such as W.A.S.P. would otherwise destroy the relation
        # clause before the release year is reached. The caller has already
        # bound this result to subject + debut relation, and ambiguity still
        # fails closed because multiple years are not rendered.
        if not _debut_release_surface_supported(field):
            continue
        if not _temporal_relation_supported(field, "release"):
            continue
        for year in re.findall(
            r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)",
            field,
        ):
            if year not in years:
                years.append(year)
    return tuple(years)


def resolve_debut_release_fact(payload, request_text):
    """Resolve one unambiguous debut-release fact from structured evidence.

    The resolver is deliberately host-side and entity-neutral. It only accepts
    results already bound to the requested subject + debut/first-album relation.
    Conflicting album titles fail closed instead of asking the model to choose.
    """
    if requested_fact_relation(request_text) != "release":
        return {}
    if not _is_debut_release_request(request_text):
        return {}

    subject = _release_subject_surface(request_text)
    if not subject:
        return {}

    titles = []
    years = []
    subject_surfaces = []
    for item in dict(payload or {}).get("results") or []:
        item_text = "\n".join((
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("page_text") or ""),
            str(item.get("pre_extracted_context") or ""),
        ))
        if not _debut_release_item_supported(item_text, request_text):
            continue

        surface = _subject_display_surface(item_text, subject)
        if surface and all(_fold(value) != _fold(surface) for value in subject_surfaces):
            subject_surfaces.append(surface)

        for title in _debut_title_candidates_from_item(item, request_text):
            if all(_fold(value) != _fold(title) for value in titles):
                titles.append(title)

        for year in _release_year_candidates_from_item(item, request_text):
            if year not in years:
                years.append(year)

    if len(titles) != 1:
        return {}

    display_subject = subject_surfaces[0] if subject_surfaces else _clean(subject)
    display_title = titles[0]
    if _fold(display_title) == _fold(display_subject):
        # Prefer the evidence-preserved entity spelling for self-titled releases
        # (for example W.A.S.P. rather than a punctuation-trimmed W.A.S.P).
        display_title = display_subject

    return {
        "subject": display_subject,
        "title": display_title,
        "year": years[0] if len(years) == 1 else "",
        "relation": "release",
    }


def deterministic_direct_fact_fallback(
    payload,
    request_text,
    requested_fact="general",
    *,
    language="hu",
):
    """Render a host-resolved direct fact only after generative grounding fails."""
    requested_fact = str(requested_fact or "general")
    fact = resolve_debut_release_fact(payload, request_text)
    if not fact:
        return ""

    return render_resolved_direct_fact(
        fact,
        requested_fact,
        language=language,
    )


def deterministic_hungarian_fact_fallback(authority_text, requested_fact="general"):
    """Return a minimal Hungarian fallback only for an explicit supported literal.

    This is intentionally not a translator or answer generator.  It is used
    only after one failed language repair, and only when the requested fact is
    an unambiguous host-extractable literal already present in evidence.
    """
    text = str(authority_text or "")
    requested_fact = str(requested_fact or "general")
    patterns = {
        "temporal": r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        "quantity": r"\b\d+(?:[.,]\d+)?\b",
        "current_value": r"\b\d+(?:[.,]\d+)?\b",
    }
    pattern = patterns.get(requested_fact)
    if not pattern:
        return ""
    match = re.search(pattern, text)
    if not match:
        return ""
    value = match.group(0)
    if requested_fact == "temporal":
        return f"A rendelkezésre álló források alapján a kért időpont: {value}."
    return f"A rendelkezésre álló források alapján a kért érték: {value}."
