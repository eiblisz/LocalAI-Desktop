import os
import shutil
from pathlib import Path


RUNTIME_ENV_VAR = "LOCALAI_DESKTOP_DATA_DIR"
APP_DATA_FOLDER = "LocalAI-Desktop"
LEGACY_MIGRATION_MARKER = ".legacy-runtime-migration-v1"


def runtime_root(env=None, home=None):
    """Return the clone-independent private runtime root for the current OS user."""
    env = os.environ if env is None else env

    override = str(env.get(RUNTIME_ENV_VAR, "") or "").strip()
    if override:
        return Path(os.path.expandvars(override)).expanduser()

    local_app_data = str(env.get("LOCALAPPDATA", "") or "").strip()
    if local_app_data:
        return Path(os.path.expandvars(local_app_data)).expanduser() / APP_DATA_FOLDER

    base_home = Path.home() if home is None else Path(home)
    return base_home / ".localai-desktop"


def _same_path(left, right):
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def _copy_missing_file(source, target):
    source = Path(source)
    target = Path(target)
    if not source.is_file() or target.exists() or _same_path(source, target):
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _copy_missing_tree(source_root, target_root, *, skip_names=()):
    source_root = Path(source_root)
    target_root = Path(target_root)
    copied = 0

    if not source_root.is_dir() or _same_path(source_root, target_root):
        return copied

    for source in source_root.rglob("*"):
        if not source.is_file() or source.name in skip_names:
            continue
        relative = source.relative_to(source_root)
        if _copy_missing_file(source, target_root / relative):
            copied += 1

    return copied


def ensure_runtime_layout(root):
    root = Path(root)
    paths = {
        "chats": root / "chats",
        "schedules": root / "schedules",
        "memory": root / "memory",
        "memory_canonical": root / "memory" / "canonical",
        "memory_vectors": root / "memory" / "vectors",
        "memory_documents": root / "memory" / "documents",
        "memory_archive": root / "memory" / "archive",
        "memory_exports": root / "memory" / "exports",
        "memory_backups": root / "memory" / "backups",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def migrate_legacy_runtime_data(repo_root, target_root):
    """
    Copy legacy repo-local private runtime data into the stable per-user root once.

    Migration is deliberately non-destructive and never overwrites an existing
    target file. The legacy source remains untouched for rollback. A marker in
    the stable root prevents deleted runtime data from being resurrected by a
    later branch/worktree launch.
    """
    repo_root = Path(repo_root)
    target_root = Path(target_root)
    layout = ensure_runtime_layout(target_root)
    marker = target_root / LEGACY_MIGRATION_MARKER

    if marker.exists():
        return {"chats": 0, "schedules": 0, "memory": 0}

    summary = {
        "chats": _copy_missing_tree(
            repo_root / "data" / "chats",
            layout["chats"],
            skip_names={".gitkeep"},
        ),
        "schedules": _copy_missing_tree(
            repo_root / "data" / "schedules",
            layout["schedules"],
            skip_names={".gitkeep"},
        ),
        "memory": 0,
    }

    legacy_memory = repo_root / "memory"
    for name, target_key in (
        ("canonical", "memory_canonical"),
        ("vectors", "memory_vectors"),
        ("documents", "memory_documents"),
        ("archive", "memory_archive"),
        ("exports", "memory_exports"),
        ("backups", "memory_backups"),
    ):
        summary["memory"] += _copy_missing_tree(
            legacy_memory / name,
            layout[target_key],
            skip_names={".gitkeep"},
        )

    marker.write_text(
        "Legacy repo-local runtime data migrated without overwriting existing target files.\n",
        encoding="utf-8",
    )
    return summary
