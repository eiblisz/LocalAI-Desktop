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
