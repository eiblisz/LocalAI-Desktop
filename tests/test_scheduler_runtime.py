from datetime import datetime
from pathlib import Path

from app.scheduler_runtime import SchedulerRuntime
from app.scheduler_store import ScheduledTaskStore
from app.storage import ChatStore


def _runtime(tmp_path: Path):
    scheduler_store = ScheduledTaskStore(tmp_path / "tasks.json")
    chat_store = ChatStore(tmp_path / "chats")
    runtime = SchedulerRuntime(
        scheduler_store,
        chat_store,
        now_provider=lambda: datetime(2026, 9, 20, 11, 30, 0),
    )
    return runtime, scheduler_store, chat_store


def test_scheduler_runtime_returns_first_due_task_id(tmp_path):
    runtime, scheduler_store, _chat_store = _runtime(tmp_path)

    first = scheduler_store.upsert({
        "name": "First",
        "prompt": "one",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    second = scheduler_store.upsert({
        "name": "Second",
        "prompt": "two",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    first["next_run_at"] = "2026-09-20T10:00:00"
    second["next_run_at"] = "2026-09-20T10:30:00"
    scheduler_store.upsert(first)
    scheduler_store.upsert(second)

    assert runtime.next_due_task_id() == first["id"]


def test_scheduler_runtime_returns_empty_when_nothing_is_due(tmp_path):
    runtime, scheduler_store, _chat_store = _runtime(tmp_path)

    task = scheduler_store.upsert({
        "name": "Later",
        "prompt": "later",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2099-01-01T00:00:00"
    scheduler_store.upsert(task)

    assert runtime.next_due_task_id() == ""


def test_scheduler_runtime_complete_creates_and_persists_schedule_chat(tmp_path):
    runtime, scheduler_store, chat_store = _runtime(tmp_path)

    task = scheduler_store.upsert({
        "name": "AI News",
        "prompt": "Summarize AI news",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })

    completion = runtime.complete(task["id"], "Fresh scheduled result.")

    assert completion.task["id"] == task["id"]
    assert completion.chat["title"] == "[SCHEDULE] AI News"
    assert completion.chat["model"] == "qwen-test"
    assert "2026-09-20 11:30" in completion.chat["messages"][-1]["content"]
    assert "Fresh scheduled result." in completion.chat["messages"][-1]["content"]

    saved_chat = chat_store.load(completion.chat["id"])
    assert saved_chat["messages"][-1]["content"] == completion.chat["messages"][-1]["content"]

    updated_task = scheduler_store.get(task["id"])
    assert updated_task["last_status"] == "success"
    assert updated_task["chat_id"] == completion.chat["id"]


def test_scheduler_runtime_complete_reuses_existing_schedule_chat(tmp_path):
    runtime, scheduler_store, chat_store = _runtime(tmp_path)

    chat = chat_store.new_chat("qwen-test")
    chat["title"] = "[SCHEDULE] Existing"
    chat_store.save(chat)

    task = scheduler_store.upsert({
        "name": "Existing",
        "prompt": "run",
        "model": "qwen-test",
        "chat_id": chat["id"],
        "frequency": "hourly",
        "enabled": True,
    })

    completion = runtime.complete(task["id"], "Second run.")

    assert completion.chat["id"] == chat["id"]
    assert chat_store.load(chat["id"])["messages"][-1]["content"].endswith(
        "Second run."
    )


def test_scheduler_runtime_failure_is_persisted(tmp_path):
    runtime, scheduler_store, _chat_store = _runtime(tmp_path)

    task = scheduler_store.upsert({
        "name": "Broken",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })

    updated = runtime.fail(task["id"], "provider unavailable")

    assert updated["last_status"] == "failed"
    assert updated["last_error"] == "provider unavailable"


def test_stale_completion_cannot_append_to_schedule_chat(tmp_path):
    runtime, scheduler_store, chat_store = _runtime(tmp_path)

    task = scheduler_store.upsert({
        "name": "Protected",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    scheduler_store.upsert(task)

    first = scheduler_store.claim_task(
        owner_id="runner-a",
        task_id=task["id"],
        now=datetime(2026, 9, 20, 11, 0, 0),
        force=True,
        lease_seconds=60,
    )
    second = scheduler_store.claim_task(
        owner_id="runner-b",
        task_id=task["id"],
        now=datetime(2026, 9, 20, 11, 2, 0),
        force=True,
        lease_seconds=600,
    )

    try:
        runtime.complete(
            task["id"],
            "stale output",
            attempt_id=first["attempt_id"],
            owner_id="runner-a",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale completion should be rejected")

    current = scheduler_store.get(task["id"])
    assert current["attempt_id"] == second["attempt_id"]
    assert not current["chat_id"]
    assert chat_store.list_chats(include_closed=True) == []
