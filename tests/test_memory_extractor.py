import json

import pytest

from app.memory_extractor import (
    MEMORY_EXTRACTION_SCHEMA,
    extract_explicit_memories,
    is_explicit_memory_request,
    validate_memory_candidate,
)


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_once(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload)


def test_explicit_memory_request_detection():
    assert is_explicit_memory_request(
        "Jegyezd meg, hogy a kedvenc shell-em PowerShell."
    )
    assert is_explicit_memory_request(
        "Remember that I prefer short answers."
    )
    assert is_explicit_memory_request(
        "Emlékezz arra, hogy a projektem neve LocalAI Desktop."
    )
    assert not is_explicit_memory_request(
        "Explain how PowerShell works."
    )


def test_extractor_returns_atomic_validated_memories():
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "Example Person",
                "key": "relationship_to_user",
                "value": "partner",
            },
            {
                "category": "PREFERENCE",
                "scope": "USER",
                "subject": "Shell",
                "key": "preferred_shell",
                "value": "PowerShell",
            },
        ]
    })

    memories = extract_explicit_memories(
        client,
        "qwen-test",
        "Jegyezd meg ezeket az adatokat.",
    )

    assert len(memories) == 2
    assert memories[0]["subject"] == "Example Person"
    assert memories[1]["value"] == "PowerShell"

    call = client.calls[0]
    assert call["model"] == "qwen-test"
    assert call["response_format"] == MEMORY_EXTRACTION_SCHEMA


def test_non_memory_request_does_not_call_model():
    client = FakeClient({"memories": []})

    memories = extract_explicit_memories(
        client,
        "qwen-test",
        "Irj egy rovid verset.",
    )

    assert memories == []
    assert client.calls == []


def test_invalid_category_fails_closed():
    with pytest.raises(ValueError, match="invalid memory category"):
        validate_memory_candidate({
            "category": "SECRET",
            "scope": "USER",
            "subject": "Example",
            "key": "example",
            "value": "example",
        })


def test_secret_candidate_fails_closed():
    with pytest.raises(ValueError, match="secret memory candidate rejected"):
        validate_memory_candidate({
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "Account",
            "key": "password",
            "value": "do-not-store",
        })


def test_invalid_json_fails_closed():
    class BadClient:
        def chat_once(self, **kwargs):
            return "not-json"

    with pytest.raises(ValueError, match="invalid JSON"):
        extract_explicit_memories(
            BadClient(),
            "qwen-test",
            "Jegyezd meg ezt.",
        )


def test_unexpected_candidate_fields_fail_closed():
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_memory_candidate({
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "Example",
            "key": "example",
            "value": "example",
            "extra": "not allowed",
        })


def test_too_many_memories_fail_closed():
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": f"Item {index}",
                "key": "fact",
                "value": "value",
            }
            for index in range(9)
        ]
    })

    with pytest.raises(ValueError, match="too many explicit memories"):
        extract_explicit_memories(
            client,
            "qwen-test",
            "Jegyezd meg ezeket.",
        )

def test_hungarian_relationship_request_uses_deterministic_two_fact_path():
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "bogus",
                "key": "name",
                "value": "bogus",
            }
        ]
    })

    memories = extract_explicit_memories(
        client,
        "qwen-test",
        "Jegyezd meg, hogy a párom Annamária és a lányom Lilla.",
    )

    assert memories == [
        {
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "Annamária",
            "key": "relationship_to_user",
            "value": "partner",
        },
        {
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "Lilla",
            "key": "relationship_to_user",
            "value": "daughter",
        },
    ]
    assert client.calls == []

def test_hungarian_self_name_request_is_normalized_to_user_profile():
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "wrong",
                "key": "wrong",
                "value": "wrong",
            }
        ]
    })

    memories = extract_explicit_memories(
        client,
        "qwen-test",
        "Jegyezd meg az en nevem Iblisz.",
    )

    assert memories == [
        {
            "category": "USER_PROFILE",
            "scope": "USER",
            "subject": "USER",
            "key": "name",
            "value": "Iblisz",
        }
    ]
    assert client.calls == []

