import json

import pytest

from app.memory_runtime import remember_explicit_request, remember_response
from app.memory_store import MemoryStore


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_once(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(self.payload)


def _relationship_payload():
    return {
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "Anna",
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
    }


def test_explicit_request_writes_atomic_candidates_to_canonical_store(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    client = FakeClient(_relationship_payload())

    written = remember_explicit_request(
        client,
        "qwen-test",
        "Jegyezd meg, hogy Anna a parom es Lilla a lanyom.",
        store,
        source_chat_id="chat-42",
    )

    assert len(written) == 2
    rows = store.list_memories(scope="USER")
    assert {row["subject"] for row in rows} == {"Anna", "Lilla"}
    assert {row["value"] for row in rows} == {"partner", "daughter"}

    for row in rows:
        sources = store.list_memory_sources(row["id"])
        assert len(sources) == 1
        assert sources[0]["source_type"] == "explicit_user"
        assert sources[0]["source_ref"] == "chat-42"
        assert "Jegyezd meg" in sources[0]["excerpt"]


def test_repeated_explicit_request_reuses_canonical_records(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    client = FakeClient(_relationship_payload())
    text = "Jegyezd meg, hogy Anna a parom es Lilla a lanyom."

    first = remember_explicit_request(
        client,
        "qwen-test",
        text,
        store,
        source_chat_id="chat-a",
    )
    second = remember_explicit_request(
        client,
        "qwen-test",
        text,
        store,
        source_chat_id="chat-b",
    )

    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert len(store.list_memories(scope="USER")) == 2

    for item in first:
        sources = store.list_memory_sources(item["id"])
        assert [source["source_ref"] for source in sources] == ["chat-a", "chat-b"]


def test_non_memory_request_does_not_write_or_call_model(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    client = FakeClient({"memories": []})

    written = remember_explicit_request(
        client,
        "qwen-test",
        "Irj egy rovid verset.",
        store,
        source_chat_id="chat-1",
    )

    assert written == []
    assert client.calls == []
    assert store.list_memories() == []


def test_invalid_extraction_fails_before_any_write(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "Safe",
                "key": "fact",
                "value": "safe",
            },
            {
                "category": "SECRET",
                "scope": "USER",
                "subject": "Invalid",
                "key": "fact",
                "value": "invalid",
            },
        ]
    })

    with pytest.raises(ValueError, match="invalid memory category"):
        remember_explicit_request(
            client,
            "qwen-test",
            "Jegyezd meg ezeket.",
            store,
        )

    assert store.list_memories() == []


def test_secret_extraction_fails_before_any_write(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    client = FakeClient({
        "memories": [
            {
                "category": "USER_PROFILE",
                "scope": "USER",
                "subject": "Account",
                "key": "password",
                "value": "do-not-store",
            }
        ]
    })

    with pytest.raises(ValueError, match="secret memory candidate rejected"):
        remember_explicit_request(
            client,
            "qwen-test",
            "Jegyezd meg ezt.",
            store,
        )

    assert store.list_memories() == []


def test_response_remember_normalizes_persists_and_deduplicates(tmp_path):
    payload = {
        "memories": [{
            "category": "PROJECT",
            "scope": "LocalAI",
            "subject": "Window memory",
            "key": "storage",
            "value": "Use the canonical SQLite store.",
        }]
    }
    client = FakeClient(payload)
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)

    first = remember_response(
        client,
        "qwen",
        "The project decision is to use the canonical SQLite store.",
        store,
        source_chat_id="chat-a",
        source_message_id="message-a",
    )
    second = remember_response(
        client,
        "gemma",
        "The project decision is to use the canonical SQLite store.",
        store,
        source_chat_id="chat-a",
        source_message_id="message-a",
    )

    assert first[0]["id"] == second[0]["id"]
    assert len(MemoryStore(path).list_memories()) == 1
    sources = store.list_memory_sources(first[0]["id"])
    assert len(sources) == 2
    assert {item["source_type"] for item in sources} == {"response_remember"}
    assert {item["source_ref"] for item in sources} == {"message-a"}
