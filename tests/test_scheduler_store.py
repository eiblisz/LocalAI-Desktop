from datetime import datetime, timedelta
from pathlib import Path

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
