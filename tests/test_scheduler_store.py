from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.scheduler_store import ScheduledTaskStore, compute_next_run


def test_compute_hourly_next_run():
    now = datetime(2026, 9, 16, 13, 0, 0)
    task = {"frequency": "hourly", "interval_hours": 2}
    assert compute_next_run(task, now) == now + timedelta(hours=2)


def test_compute_daily_next_run_rolls_to_tomorrow():
    now = datetime(2026, 9, 16, 13, 0, 0)
    task = {"frequency": "daily", "daily_time": "08:00"}
    assert compute_next_run(task, now) == datetime(2026, 9, 17, 8, 0, 0)


def test_store_persists_and_detects_due_task(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Weather",
        "prompt": "Check weather",
        "model": "qwen-test",
        "location": "Bad Nenndorf, Germany",
        "frequency": "hourly",
        "interval_hours": 1,
        "enabled": True,
        "permissions": {"weather": True},
    })

    task["next_run_at"] = "2026-09-16T12:00:00"
    store.upsert(task)

    due = store.due_tasks(datetime(2026, 9, 16, 13, 0, 0))
    assert [item["id"] for item in due] == [task["id"]]


def test_mark_result_records_status_and_moves_next_run(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Weather",
        "prompt": "Check weather",
        "model": "qwen-test",
        "location": "Berlin",
        "frequency": "hourly",
        "interval_hours": 1,
        "enabled": True,
        "permissions": {"weather": True},
    })

    updated = store.mark_result(
        task["id"],
        status="success",
        chat_id="chat-123",
    )

    assert updated["last_status"] == "success"
    assert updated["chat_id"] == "chat-123"
    assert updated["last_run_at"]
    assert updated["next_run_at"]


def test_compute_weekly_next_run():
    now = datetime(2026, 9, 16, 13, 0, 0)  # Wednesday
    task = {
        "frequency": "weekly",
        "weekly_day": 4,  # Friday
        "daily_time": "18:30",
    }
    assert compute_next_run(task, now) == datetime(2026, 9, 18, 18, 30, 0)


def test_compute_weekly_rolls_one_week_when_time_has_passed():
    now = datetime(2026, 9, 18, 20, 0, 0)  # Friday
    task = {
        "frequency": "weekly",
        "weekly_day": 4,
        "daily_time": "18:30",
    }
    assert compute_next_run(task, now) == datetime(2026, 9, 25, 18, 30, 0)


def test_compute_custom_interval_minutes():
    now = datetime(2026, 9, 16, 14, 0, 0)
    task = {
        "frequency": "custom_interval",
        "custom_interval_value": 15,
        "custom_interval_unit": "minutes",
    }
    assert compute_next_run(task, now) == datetime(2026, 9, 16, 14, 15, 0)


def test_compute_custom_interval_hours_and_days():
    now = datetime(2026, 9, 16, 14, 0, 0)

    hours = {
        "frequency": "custom_interval",
        "custom_interval_value": 6,
        "custom_interval_unit": "hours",
    }
    days = {
        "frequency": "custom_interval",
        "custom_interval_value": 2,
        "custom_interval_unit": "days",
    }

    assert compute_next_run(hours, now) == datetime(2026, 9, 16, 20, 0, 0)
    assert compute_next_run(days, now) == datetime(2026, 9, 18, 14, 0, 0)


def test_claim_task_grants_one_active_lease(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Lease test",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    store.upsert(task)

    first = store.claim_task(
        owner_id="desktop-a",
        now=datetime(2026, 9, 20, 11, 0, 0),
        lease_seconds=600,
    )
    second = store.claim_task(
        owner_id="runner-b",
        now=datetime(2026, 9, 20, 11, 0, 1),
        lease_seconds=600,
    )

    assert first is not None
    assert first["id"] == task["id"]
    assert first["lease_owner"] == "desktop-a"
    assert first["attempt_id"]
    assert first["last_status"] == "running"
    assert first["attempt_count"] == 1
    assert second is None


def test_expired_scheduler_lease_can_be_reclaimed(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Recovery",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    store.upsert(task)

    first = store.claim_task(
        owner_id="runner-a",
        now=datetime(2026, 9, 20, 11, 0, 0),
        lease_seconds=60,
    )
    recovered = store.claim_task(
        owner_id="runner-b",
        now=datetime(2026, 9, 20, 11, 2, 0),
        lease_seconds=60,
    )

    assert first is not None
    assert recovered is not None
    assert recovered["attempt_id"] != first["attempt_id"]
    assert recovered["lease_owner"] == "runner-b"
    assert recovered["attempt_count"] == 2


def test_stale_scheduler_attempt_cannot_overwrite_newer_result(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Stale guard",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    store.upsert(task)

    first = store.claim_task(
        owner_id="runner-a",
        now=datetime(2026, 9, 20, 11, 0, 0),
        lease_seconds=60,
    )
    second = store.claim_task(
        owner_id="runner-b",
        now=datetime(2026, 9, 20, 11, 2, 0),
        lease_seconds=600,
    )

    with pytest.raises(RuntimeError, match="stale scheduler attempt"):
        store.mark_result(
            task["id"],
            status="success",
            attempt_id=first["attempt_id"],
            owner_id="runner-a",
            now=datetime(2026, 9, 20, 11, 2, 30),
        )

    updated = store.mark_result(
        task["id"],
        status="success",
        attempt_id=second["attempt_id"],
        owner_id="runner-b",
        now=datetime(2026, 9, 20, 11, 3, 0),
    )

    assert updated["last_status"] == "success"
    assert updated["last_attempt_id"] == second["attempt_id"]
    assert updated["attempt_id"] == ""
    assert updated["lease_owner"] == ""
    assert updated["lease_until"] == ""


def test_task_edit_preserves_active_execution_authority(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Editable",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    store.upsert(task)

    claimed = store.claim_task(
        owner_id="runner-a",
        task_id=task["id"],
        now=datetime(2026, 9, 20, 11, 0, 0),
        force=True,
        lease_seconds=600,
    )
    edited = store.get(task["id"])
    for field in (
        "lease_owner",
        "lease_until",
        "attempt_id",
        "attempt_started_at",
        "attempt_count",
        "last_attempt_id",
    ):
        edited.pop(field, None)
    edited["name"] = "Renamed while running"

    saved = store.upsert(edited)

    assert saved["name"] == "Renamed while running"
    assert saved["lease_owner"] == "runner-a"
    assert saved["attempt_id"] == claimed["attempt_id"]
    assert saved["attempt_count"] == 1


def test_active_lease_requires_attempt_and_owner_to_record_result(tmp_path: Path):
    store = ScheduledTaskStore(tmp_path / "tasks.json")
    task = store.upsert({
        "name": "Authority required",
        "prompt": "run",
        "model": "qwen-test",
        "frequency": "hourly",
        "enabled": True,
    })
    task["next_run_at"] = "2026-09-20T10:00:00"
    store.upsert(task)

    claim = store.claim_task(
        owner_id="runner-a",
        task_id=task["id"],
        now=datetime(2026, 9, 20, 11, 0, 0),
        force=True,
        lease_seconds=600,
    )

    with pytest.raises(RuntimeError, match="attempt_id is required"):
        store.mark_result(
            task["id"],
            status="success",
            now=datetime(2026, 9, 20, 11, 1, 0),
        )

    updated = store.mark_result(
        task["id"],
        status="success",
        attempt_id=claim["attempt_id"],
        owner_id="runner-a",
        now=datetime(2026, 9, 20, 11, 1, 0),
    )
    assert updated["last_status"] == "success"
