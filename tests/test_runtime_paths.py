from pathlib import Path

from app.runtime_paths import (
    RUNTIME_ENV_VAR,
    ensure_runtime_layout,
    migrate_legacy_runtime_data,
    runtime_root,
)


def test_runtime_root_prefers_explicit_override(tmp_path):
    override = tmp_path / "private-runtime"
    root = runtime_root({RUNTIME_ENV_VAR: str(override), "LOCALAPPDATA": "ignored"})

    assert root == override


def test_runtime_root_uses_localappdata_on_windows_style_environment(tmp_path):
    root = runtime_root({"LOCALAPPDATA": str(tmp_path)}, home=tmp_path / "home")

    assert root == tmp_path / "LocalAI-Desktop"


def test_runtime_root_has_home_fallback(tmp_path):
    root = runtime_root({}, home=tmp_path)

    assert root == tmp_path / ".localai-desktop"


def test_runtime_layout_is_clone_independent(tmp_path):
    root = tmp_path / "runtime"
    paths = ensure_runtime_layout(root)

    assert paths["chats"] == root / "chats"
    assert paths["schedules"] == root / "schedules"
    assert paths["memory_canonical"] == root / "memory" / "canonical"
    assert all(path.is_dir() for path in paths.values())


def test_legacy_runtime_migration_copies_private_data_without_overwrite(tmp_path):
    repo = tmp_path / "clone-a"
    target = tmp_path / "stable-runtime"

    (repo / "data" / "chats").mkdir(parents=True)
    (repo / "data" / "schedules").mkdir(parents=True)
    (repo / "memory" / "canonical").mkdir(parents=True)
    (repo / "memory" / "backups").mkdir(parents=True)

    (repo / "data" / "chats" / "chat-1.json").write_text(
        '{"title":"old chat"}',
        encoding="utf-8",
    )
    (repo / "data" / "schedules" / "tasks.json").write_text(
        '[{"name":"AI Hirek"}]',
        encoding="utf-8",
    )
    (repo / "memory" / "canonical" / "memory.sqlite3").write_bytes(b"legacy-db")
    (repo / "memory" / "backups" / "before.sqlite3").write_bytes(b"backup-db")
    (repo / "memory" / "backups" / ".gitkeep").write_text("", encoding="utf-8")

    first = migrate_legacy_runtime_data(repo, target)

    assert first == {"chats": 1, "schedules": 1, "memory": 2}
    assert (target / "chats" / "chat-1.json").read_text(encoding="utf-8") == '{"title":"old chat"}'
    assert (target / "schedules" / "tasks.json").read_text(encoding="utf-8") == '[{"name":"AI Hirek"}]'
    assert (target / "memory" / "canonical" / "memory.sqlite3").read_bytes() == b"legacy-db"
    assert (target / "memory" / "backups" / "before.sqlite3").read_bytes() == b"backup-db"
    assert not (target / "memory" / "backups" / ".gitkeep").exists()

    (target / "chats" / "chat-1.json").write_text(
        '{"title":"newer target chat"}',
        encoding="utf-8",
    )

    second = migrate_legacy_runtime_data(repo, target)

    assert second == {"chats": 0, "schedules": 0, "memory": 0}
    assert (
        target / "chats" / "chat-1.json"
    ).read_text(encoding="utf-8") == '{"title":"newer target chat"}'


def test_migration_from_another_clone_uses_same_target(tmp_path):
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"
    target = tmp_path / "stable-runtime"

    (clone_a / "data" / "chats").mkdir(parents=True)
    (clone_b / "data" / "chats").mkdir(parents=True)
    (clone_a / "data" / "chats" / "a.json").write_text("{}", encoding="utf-8")
    (clone_b / "data" / "chats" / "b.json").write_text("{}", encoding="utf-8")

    migrate_legacy_runtime_data(clone_a, target)
    migrate_legacy_runtime_data(clone_b, target)

    assert sorted(path.name for path in (target / "chats").glob("*.json")) == [
        "a.json",
        "b.json",
    ]
