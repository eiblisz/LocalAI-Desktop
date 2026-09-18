from app.memory_answers import direct_user_memory_answer


MEMORIES = [
    {
        "category": "USER_PROFILE",
        "scope": "USER",
        "subject": "USER",
        "key": "name",
        "value": "Iblisz",
        "status": "active",
    },
    {
        "category": "USER_PROFILE",
        "scope": "USER",
        "subject": "Lilla",
        "key": "relationship_to_user",
        "value": "daughter",
        "status": "active",
    },
    {
        "category": "USER_PROFILE",
        "scope": "USER",
        "subject": "Annamária",
        "key": "relationship_to_user",
        "value": "partner",
        "status": "active",
    },
]


def test_hungarian_direct_user_memory_questions_use_second_person():
    answer = direct_user_memory_answer(
        "Ki Iblisz?\nKi nekem Lilla?\nKi nekem Annamária?",
        MEMORIES,
    )

    assert answer == (
        "A neved Iblisz.\n\n"
        "Lilla a lányod.\n\n"
        "Annamária a párod."
    )


def test_hungarian_reverse_relationship_query_uses_user_perspective():
    assert (
        direct_user_memory_answer("Ki a lányom?", MEMORIES)
        == "Lilla a lányod."
    )


def test_hungarian_own_name_query_uses_user_perspective():
    assert (
        direct_user_memory_answer("Mi a nevem?", MEMORIES)
        == "A neved Iblisz."
    )


def test_english_direct_questions_use_second_person():
    answer = direct_user_memory_answer(
        "Who is Iblisz?\nWho is Lilla?",
        MEMORIES,
    )

    assert answer == (
        "Your name is Iblisz.\n\n"
        "Lilla is your daughter."
    )


def test_unrelated_or_partial_request_fails_closed():
    assert direct_user_memory_answer("Ki Iblisz? És milyen az idő?", MEMORIES) == ""


def test_non_profile_memory_is_not_used():
    memories = [
        {
            "category": "PROJECT",
            "scope": "USER",
            "subject": "Iblisz",
            "key": "name",
            "value": "Not the user",
            "status": "active",
        }
    ]
    assert direct_user_memory_answer("Ki Iblisz?", memories) == ""


PERSON_RELATION_MEMORIES = MEMORIES + [
    {
        "category": "USER_PROFILE",
        "scope": "USER",
        "subject": "Kristof",
        "key": "son_of",
        "value": "Annamaria",
        "status": "active",
    },
]


def test_third_person_relation_answers_without_claiming_user_relationship():
    assert (
        direct_user_memory_answer("Ki Kristof?", PERSON_RELATION_MEMORIES)
        == "Kristof Annamaria fia."
    )


def test_reverse_third_person_relation_query_is_supported():
    assert (
        direct_user_memory_answer("Ki Annamaria fia?", PERSON_RELATION_MEMORIES)
        == "Kristof Annamaria fia."
    )


def test_asking_relationship_to_user_does_not_infer_from_third_person_relation():
    assert (
        direct_user_memory_answer("Ki nekem Kristof?", PERSON_RELATION_MEMORIES)
        == (
            "Kristof Annamaria fia. "
            "A hozzád való kapcsolatáról nincs eltett adat."
        )
    )


def test_known_user_relationship_still_has_priority():
    assert (
        direct_user_memory_answer("Ki Annamária?", PERSON_RELATION_MEMORIES)
        == "Annamária a párod."
    )

