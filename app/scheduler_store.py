import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .config import SCHEDULE_DIR


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _next_daily(now, hhmm):
    try:
        hour, minute = [int(part) for part in str(hhmm).split(":", 1)]
    except Exception:
        hour, minute = 8, 0

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def compute_next_run(task, now=None):
    now = now or datetime.now()
    frequency = task.get("frequency", "hourly")

    if frequency == "daily":
        return _next_daily(now, task.get("daily_time", "08:00"))

    interval = max(1, int(task.get("interval_hours", 1) or 1))
    return now + timedelta(hours=interval)


class ScheduledTaskStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (SCHEDULE_DIR / "tasks.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self):
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    def _save_all(self, tasks):
        self.path.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize(task):
        task = dict(task)
        task.setdefault("id", uuid.uuid4().hex)
        task.setdefault("name", "Scheduled task")
        task.setdefault("prompt", "")
        task.setdefault("location", "")
        task.setdefault("ebay_query", "")
        task.setdefault("ebay_max_results", 8)
        task.setdefault("model", "")
        task.setdefault("frequency", "hourly")
        task.setdefault("interval_hours", 1)
        task.setdefault("daily_time", "08:00")
        task.setdefault("enabled", True)
        permissions = task.setdefault("permissions", {"weather": False})
        if "task_type" not in task:
            task["task_type"] = (
                "weather"
                if permissions.get("weather", False)
                else "custom"
            )
        task.setdefault("chat_id", "")
        task.setdefault("last_run_at", "")
        task.setdefault("last_status", "never")
        task.setdefault("last_error", "")
        task.setdefault("next_run_at", "")
        return task

    def list_tasks(self):
        return [self._normalize(item) for item in self._load_all()]

    def get(self, task_id):
        for task in self.list_tasks():
            if task["id"] == task_id:
                return task
        raise KeyError(task_id)

    def upsert(self, task):
        tasks = self.list_tasks()
        item = self._normalize(task)
        existing = next((i for i, t in enumerate(tasks) if t["id"] == item["id"]), None)

        if not item.get("next_run_at"):
            item["next_run_at"] = compute_next_run(item).isoformat(timespec="seconds")

        if existing is None:
            tasks.append(item)
        else:
            tasks[existing] = item

        self._save_all(tasks)
        return item

    def delete(self, task_id):
        tasks = [task for task in self.list_tasks() if task["id"] != task_id]
        self._save_all(tasks)

    def due_tasks(self, now=None):
        now = now or datetime.now()
        due = []
        for task in self.list_tasks():
            if not task.get("enabled", True):
                continue
            next_run = _parse_iso(task.get("next_run_at"))
            if next_run is None:
                task["next_run_at"] = compute_next_run(task, now).isoformat(timespec="seconds")
                self.upsert(task)
                continue
            if next_run <= now:
                due.append(task)

        return sorted(due, key=lambda task: task.get("next_run_at", ""))

    def mark_result(self, task_id, status, error="", chat_id=""):
        task = self.get(task_id)
        now = datetime.now()
        task["last_run_at"] = now.isoformat(timespec="seconds")
        task["last_status"] = status
        task["last_error"] = error
        if chat_id:
            task["chat_id"] = chat_id
        task["next_run_at"] = compute_next_run(task, now).isoformat(timespec="seconds")
        return self.upsert(task)
