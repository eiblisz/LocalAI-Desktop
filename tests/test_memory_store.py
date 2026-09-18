import sqlite3

import pytest

from app.memory_store import MemoryStore


def test_memory_store_creates_expected_schema(tmp_path):
    path = tmp_path / "memory.sqlite3"
    MemoryStore(path)

    with sqlite3.connect(path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "memories",
        "memory_sources",
        "memory_links",
        "memory_conflicts",
        "lessons",
    }.issubset(tables)


def test_add_and_list_memory_respects_scope_and_importance(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    normal = store.add_memory(
        category="preference",
        scope="USER",
        subject="shopping",
        key="delivery",
        value="prefer faster delivery",
        importance="REMEMBER",
    )
    pinned = store.add_memory(
        category="rule",
        scope="USER",
        subject="shopping",
        key="condition",
        value="prefer new hardware when price difference is small",
        importance="PINNED",
    )
    store.add_memory(
        category="project",
        scope="PROJECT: LocalAI-Desktop",
        subject="runtime",
        key="platform",
        value="Windows desktop",
    )

    rows = store.list_memories(scope="USER")

    assert [row["id"] for row in rows] == [pinned["id"], normal["id"]]
    assert all(row["scope"] == "USER" for row in rows)


def test_superseding_memory_marks_old_value_inactive(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    old = store.add_memory(
        category="user_profile",
        scope="USER",
        subject="PC",
        key="ram_target",
        value="32GB",
    )
    new = store.add_memory(
        category="user_profile",
        scope="USER",
        subject="PC",
        key="ram_target",
        value="64GB",
        supersedes_id=old["id"],
    )

    assert store.get_memory(old["id"])["status"] == "superseded"
    assert new["status"] == "active"
    assert new["supersedes_id"] == old["id"]
    assert [row["id"] for row in store.list_memories(scope="USER")] == [new["id"]]


def test_archive_and_delete_remove_memory_from_default_retrieval(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    archived = store.add_memory(
        category="working",
        scope="CHAT ONLY",
        subject="task",
        key="state",
        value="temporary context",
    )
    deleted = store.add_memory(
        category="working",
        scope="CHAT ONLY",
        subject="task",
        key="note",
        value="temporary note",
    )

    store.archive_memory(archived["id"])
    store.delete_memory(deleted["id"])

    assert store.list_memories(scope="CHAT ONLY") == []
    assert store.get_memory(archived["id"])["status"] == "archived"
    assert store.get_memory(deleted["id"])["status"] == "deleted"


def test_secret_guard_rejects_sensitive_keys_and_values(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    with pytest.raises(ValueError, match="secret memory rejected"):
        store.add_memory(
            category="user_profile",
            scope="USER",
            subject="Brave",
            key="api_key",
            value="not-a-real-key",
        )

    with pytest.raises(ValueError, match="secret memory rejected"):
        store.add_memory(
            category="user_profile",
            scope="USER",
            subject="SSH",
            key="credential",
            value="-----BEGIN PRIVATE KEY----- abc",
        )


def test_secret_guard_does_not_reject_non_secret_profile_data(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    memory = store.add_memory(
        category="user_profile",
        scope="USER",
        subject="PC",
        key="motherboard",
        value="MSI PRO H610 DDR4",
        importance="IMPORTANT",
    )

    assert memory["status"] == "active"
    assert memory["value"] == "MSI PRO H610 DDR4"


def test_mark_used_updates_last_used_at(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    memory = store.add_memory(
        category="project",
        scope="PROJECT: LocalAI-Desktop",
        subject="memory",
        key="backend",
        value="SQLite",
    )

    assert memory["last_used_at"] is None
    used = store.mark_used(memory["id"])
    assert used["last_used_at"] is not None


def test_invalid_category_importance_and_confidence_fail_closed(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    with pytest.raises(ValueError, match="invalid category"):
        store.add_memory(
            category="secret",
            scope="USER",
            subject="x",
            key="x",
            value="x",
        )

    with pytest.raises(ValueError, match="invalid importance"):
        store.add_memory(
            category="working",
            scope="USER",
            subject="x",
            key="x",
            value="x",
            importance="FOREVER",
        )

    with pytest.raises(ValueError, match="confidence"):
        store.add_memory(
            category="working",
            scope="USER",
            subject="x",
            key="x",
            value="x",
            confidence=1.5,
        )


def test_default_memory_db_is_canonical_private_store():
    from app.memory_store import DEFAULT_MEMORY_DB
    from app.config import ROOT_DIR

    assert DEFAULT_MEMORY_DB == ROOT_DIR / "memory" / "canonical" / "memory.sqlite3"
