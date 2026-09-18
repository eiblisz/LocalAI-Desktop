import re
import unicodedata


_RELATIONSHIP_HU = {
    "partner": "párod",
    "daughter": "lányod",
    "son": "fiad",
    "husband": "férjed",
    "wife": "feleséged",
    "mother": "anyád",
    "father": "apád",
    "sibling": "testvéred",
}

_RELATIONSHIP_EN = {
    "partner": "partner",
    "daughter": "daughter",
    "son": "son",
    "husband": "husband",
    "wife": "wife",
    "mother": "mother",
    "father": "father",
    "sibling": "sibling",
}

_PERSON_RELATION_HU = {
    "son_of": "fia",
    "daughter_of": "lánya",
    "husband_of": "férje",
    "wife_of": "felesége",
    "girlfriend_of": "barátnője",
    "boyfriend_of": "barátja",
    "mother_of": "anyja",
    "father_of": "apja",
    "sibling_of": "testvére",
    "partner_of": "párja",
}

_PERSON_RELATION_EN = {
    "son_of": "son",
    "daughter_of": "daughter",
    "husband_of": "husband",
    "wife_of": "wife",
    "girlfriend_of": "girlfriend",
    "boyfriend_of": "boyfriend",
    "mother_of": "mother",
    "father_of": "father",
    "sibling_of": "sibling",
    "partner_of": "partner",
}

_HU_RELATION_QUERY = {
    "parom": "partner",
    "partnerem": "partner",
    "lanyom": "daughter",
    "fiam": "son",
    "ferjem": "husband",
    "felesegem": "wife",
    "anyam": "mother",
    "apam": "father",
    "testverem": "sibling",
}

_HU_PERSON_RELATION_QUERY = {
    "fia": "son_of",
    "lanya": "daughter_of",
    "ferje": "husband_of",
    "felesege": "wife_of",
    "baratnoje": "girlfriend_of",
    "baratja": "boyfriend_of",
    "anyja": "mother_of",
    "apja": "father_of",
    "testvere": "sibling_of",
    "parja": "partner_of",
}


def _clean(value):
    return " ".join(str(value or "").strip().split())


def _fold(value):
    text = unicodedata.normalize("NFKD", _clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def _question_parts(query):
    raw_parts = re.split(r"[?\n]+", str(query or ""))
    return [part.strip(" \t\r\n.,!;:") for part in raw_parts if part.strip()]


def _active_user_profile(memories):
    rows = []
    for memory in memories or []:
        if str(memory.get("status", "active")) != "active":
            continue
        if str(memory.get("category", "")).upper() != "USER_PROFILE":
            continue
        if str(memory.get("scope", "USER")).upper() != "USER":
            continue
        rows.append(memory)
    return rows


def _user_name_memory(memories):
    matches = [
        memory
        for memory in memories
        if _fold(memory.get("key")) in {"name", "user_name", "preferred_name"}
    ]
    if len(matches) == 1:
        return matches[0]
    return matches[0] if matches else None


def _relationship_memories(memories):
    return [
        memory
        for memory in memories
        if _fold(memory.get("key")) == "relationship_to_user"
    ]


def _person_relationship_memories(memories):
    allowed = set(_PERSON_RELATION_HU)
    return [
        memory
        for memory in memories
        if _fold(memory.get("key")) in allowed
    ]


def _is_hungarian(text):
    folded = _fold(text)
    markers = (
        "ki ",
        "ki nekem",
        "mi a nevem",
        "hogy hivnak",
        "nevem",
        "lanyom",
        "parom",
        "fiam",
        "ferjem",
        "felesegem",
        "anyam",
        "apam",
        "testverem",
        "fia",
        "lanya",
        "ferje",
        "felesege",
        "baratnoje",
        "baratja",
        "anyja",
        "apja",
        "testvere",
        "parja",
    )
    return any(marker in folded for marker in markers)


def _format_person_relation(memory, *, hungarian):
    subject = _clean(memory.get("subject"))
    relation = _fold(memory.get("key"))
    related = _clean(memory.get("value"))
    if not subject or not related:
        return ""

    if hungarian:
        relation_text = _PERSON_RELATION_HU.get(relation)
        if not relation_text:
            return ""
        return f"{subject} {related} {relation_text}."

    relation_text = _PERSON_RELATION_EN.get(relation)
    if not relation_text:
        return ""
    return f"{subject} is {related}'s {relation_text}."


def _answer_part(part, profiles):
    folded = _fold(part)
    is_hu = _is_hungarian(part)

    name_memory = _user_name_memory(profiles)
    if name_memory is not None:
        name = _clean(name_memory.get("value"))
        name_folded = _fold(name)
        asks_own_name = any(
            marker in folded
            for marker in (
                "mi a nevem",
                "hogy hivnak",
                "what is my name",
                "whats my name",
            )
        )
        asks_about_saved_name = bool(
            name_folded
            and name_folded in folded
            and (
                folded.startswith("ki ")
                or folded.startswith("who ")
                or " ki " in f" {folded} "
                or " who " in f" {folded} "
            )
        )
        if asks_own_name or asks_about_saved_name:
            return f"A neved {name}." if is_hu else f"Your name is {name}."

    person_relationships = _person_relationship_memories(profiles)

    # A specific third-person reverse query such as "Ki Annamaria fia?"
    # must outrank a broader USER relationship match on "Annamaria".
    if is_hu:
        for query_term, canonical in _HU_PERSON_RELATION_QUERY.items():
            if query_term not in folded:
                continue
            matches = [
                memory
                for memory in person_relationships
                if _fold(memory.get("key")) == canonical
                and _fold(memory.get("value")) in folded
            ]
            if len(matches) == 1:
                return _format_person_relation(matches[0], hungarian=True)

    relationships = _relationship_memories(profiles)

    for memory in relationships:
        subject = _clean(memory.get("subject"))
        relation = _fold(memory.get("value"))
        if subject and _fold(subject) in folded:
            if is_hu:
                relation_text = _RELATIONSHIP_HU.get(relation)
                if relation_text:
                    return f"{subject} a {relation_text}."
            relation_text = _RELATIONSHIP_EN.get(relation)
            if relation_text:
                return f"{subject} is your {relation_text}."

    if is_hu:
        for query_term, canonical in _HU_RELATION_QUERY.items():
            if query_term not in folded:
                continue
            matches = [
                memory
                for memory in relationships
                if _fold(memory.get("value")) == canonical
            ]
            if len(matches) == 1:
                subject = _clean(matches[0].get("subject"))
                relation_text = _RELATIONSHIP_HU.get(canonical)
                if subject and relation_text:
                    return f"{subject} a {relation_text}."

    asks_user_relation = (
        "nekem" in folded
        or "hozzam" in folded
        or "hozzám" in part.casefold()
        or " my " in f" {folded} "
    )

    for memory in person_relationships:
        subject = _clean(memory.get("subject"))
        if subject and _fold(subject) in folded:
            relation_text = _format_person_relation(memory, hungarian=is_hu)
            if not relation_text:
                continue
            if asks_user_relation:
                if is_hu:
                    return (
                        relation_text
                        + " A hozzád való kapcsolatáról nincs eltett adat."
                    )
                return (
                    relation_text
                    + " There is no saved relationship between this person and you."
                )
            return relation_text

    return ""


def direct_user_memory_answer(query, memories):
    """
    Return a deterministic answer for simple direct USER_PROFILE questions.

    Fail closed: if any question part cannot be answered deterministically,
    return an empty string so the normal model path handles the whole request.
    """
    parts = _question_parts(query)
    if not parts:
        return ""

    profiles = _active_user_profile(memories)
    if not profiles:
        return ""

    answers = []
    for part in parts:
        answer = _answer_part(part, profiles)
        if not answer:
            return ""
        answers.append(answer)

    return "\n\n".join(answers)
