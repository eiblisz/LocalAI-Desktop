from datetime import datetime
from pathlib import Path

from app.scheduler_engine import SchedulerEngine
from app.scheduler_store import ScheduledTaskStore
from app.scheduled_task_executor import ScheduledExecutionResult
from app.storage import ChatStore


class DummyClient:
    pass


class SuccessExecutor:
    def __init__(self, client):
        self.client = client

    def execute(self, task):
        return ScheduledExecutionResult(
            content=f"Completed {task['name']}"
        )


class FailingExecutor:
    def __init__(self, client):
        self.client = client

    def execute(self, task):
        raise RuntimeError("executor failed")


def _engine(tmp_path: Path, *, executor_factory, owner_id="runner-a"):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    chats = ChatStore(tmp_path / "chats")
    now = lambda: datetime(2026, 9, 20, 12, 0, 0)
    engine = SchedulerEngine(
        store,
        chats,
        DummyClient(),
        owner_id=owner_id,
        now_provider=now,
        lease_seconds=600,
        executor_factory=executor_factory,
    )
    return engine, store, chats


def _due_task(store):
    task = store.upsert({
        "name": "Due task",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T11:00:00"
    return store.upsert(task)


def test_scheduler_engine_is_idle_when_no_task_is_due(tmp_path):
    engine, _store, _chats = _engine(
        tmp_path,
        executor_factory=SuccessExecutor,
    )

    result = engine.run_once()

    assert result.status == "idle"
    assert result.task_id == ""


def test_scheduler_engine_claims_executes_and_persists_success(tmp_path):
    engine, store, chats = _engine(
        tmp_path,
        executor_factory=SuccessExecutor,
    )
    task = _due_task(store)

    result = engine.run_once()

    assert result.status == "success"
    assert result.task_id == task["id"]
    assert result.attempt_id

    saved = store.get(task["id"])
    assert saved["last_status"] == "success"
    assert saved["last_attempt_id"] == result.attempt_id
    assert saved["lease_owner"] == ""
    assert saved["attempt_id"] == ""
    assert saved["chat_id"]

    chat = chats.load(saved["chat_id"])
    assert chat["title"] == "[SCHEDULE] Due task"
    assert "Completed Due task" in chat["messages"][-1]["content"]


def test_scheduler_engine_persists_executor_failure(tmp_path):
    engine, store, _chats = _engine(
        tmp_path,
        executor_factory=FailingExecutor,
    )
    task = _due_task(store)

    result = engine.run_once()

    assert result.status == "failed"
    assert result.task_id == task["id"]
    assert "executor failed" in result.message

    saved = store.get(task["id"])
    assert saved["last_status"] == "failed"
    assert saved["last_error"] == "executor failed"
    assert saved["lease_owner"] == ""
    assert saved["attempt_id"] == ""


def test_second_engine_cannot_run_task_with_active_lease(tmp_path):
    first, store, chats = _engine(
        tmp_path,
        executor_factory=SuccessExecutor,
        owner_id="runner-a",
    )
    task = _due_task(store)

    claimed = first.claim_next_due()
    assert claimed is not None

    second = SchedulerEngine(
        store,
        chats,
        DummyClient(),
        owner_id="runner-b",
        now_provider=lambda: datetime(2026, 9, 20, 12, 0, 1),
        lease_seconds=600,
        executor_factory=SuccessExecutor,
    )

    result = second.run_once()

    assert result.status == "idle"
    still_running = store.get(task["id"])
    assert still_running["lease_owner"] == "runner-a"
    assert still_running["attempt_id"] == claimed["attempt_id"]



def test_default_scheduler_client_claims_scheduler_resource_owner(monkeypatch, tmp_path):
    captured = {}

    class CapturingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.scheduler_engine.OllamaClient", CapturingClient)

    SchedulerEngine(
        ScheduledTaskStore(tmp_path / "tasks-owner.json"),
        ChatStore(tmp_path / "chats-owner"),
        owner_id="runner-owner-test",
    )

    assert captured["auto_prepare_model"] is True
    assert captured["owner_type"] == "SCHEDULER"
    assert captured["owner_id"] == "runner-owner-test"



def test_background_scheduler_releases_owned_model_after_task(tmp_path):
    class ReleasingClient:
        def __init__(self):
            self.releases = []

        def release_owned_models(self, timeout=5.0):
            self.releases.append(timeout)
            return {"released": ["qwen-test"], "blocked": [], "reconciled": []}

    store = ScheduledTaskStore(tmp_path / "tasks-release.json")
    chats = ChatStore(tmp_path / "chats-release")
    client = ReleasingClient()
    engine = SchedulerEngine(
        store,
        chats,
        client,
        owner_id="runner-release",
        now_provider=lambda: datetime(2026, 9, 20, 12, 0, 0),
        lease_seconds=600,
        executor_factory=SuccessExecutor,
    )
    _due_task(store)

    result = engine.run_once()

    assert result.status == "success"
    assert client.releases == [5.0]
