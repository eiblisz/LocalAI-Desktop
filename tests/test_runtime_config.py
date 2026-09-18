def test_private_runtime_paths_share_stable_root():
    from app.config import (
        CHAT_DIR,
        MEMORY_CANONICAL_DIR,
        RUNTIME_DIR,
        SCHEDULE_DIR,
    )

    assert CHAT_DIR == RUNTIME_DIR / "chats"
    assert SCHEDULE_DIR == RUNTIME_DIR / "schedules"
    assert MEMORY_CANONICAL_DIR == RUNTIME_DIR / "memory" / "canonical"


def test_artifact_output_remains_repository_local():
    from app.config import OUTPUT_DIR, ROOT_DIR

    assert OUTPUT_DIR == ROOT_DIR / "output"
