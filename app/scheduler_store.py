import json
import os
import uuid
from contextlib import contextmanager
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


def _time_parts(hhmm):
    try:
        return [int(part) for part in str(hhmm).split(":", 1)]
    except Exception:
        return [8, 0]


def _next_daily(now, hhmm):
    hour, minute = _time_parts(hhmm)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly(now, weekday, hhmm):
    hour, minute = _time_parts(hhmm)
    target = max(0, min(int(weekday or 0), 6))
    days_ahead = (target - now.weekday()) % 7
    candidate = (
        now + timedelta(days=days_ahead)
    ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def compute_next_run(task, now=None):
    now = now or datetime.now()
    frequency = task.get("frequency", "hourly")

    if frequency == "daily":
        return _next_daily(now, task.get("daily_time", "08:00"))

    if frequency == "weekly":
        return _next_weekly(
            now,
            task.get("weekly_day", 0),
            task.get("daily_time", "08:00"),
        )

    if frequency == "custom_interval":
        value = max(1, int(task.get("custom_interval_value", 15) or 15))
        unit = str(task.get("custom_interval_unit", "minutes")).lower()
        if unit == "days":
            return now + timedelta(days=value)
        if unit == "hours":
            return now + timedelta(hours=value)
        return now + timedelta(minutes=value)

    interval = max(1, int(task.get("interval_hours", 1) or 1))
    return now + timedelta(hours=interval)


class ScheduledTaskStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (SCHEDULE_DIR / "tasks.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _exclusive_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if handle.read(1) == b"":
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_all(self):
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    def _save_all(self, tasks):
        temp_path = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(tasks, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _normalize(task):
        task = dict(task)
        task.setdefault("id", uuid.uuid4().hex)
        task.setdefault("name", "Scheduled task")
        task.setdefault("prompt", "")
        task.setdefault("location", "")
        task.setdefault("ebay_query", "")
        task.setdefault("ebay_max_results", 8)
        task.setdefault("web_search_enabled", False)
        task.setdefault("web_query", "")
        task.setdefault("web_max_results", 6)
        task.setdefault("web_fetch_pages", True)
        task.setdefault("model", "")
        task.setdefault("frequency", "hourly")
        task.setdefault("interval_hours", 1)
        task.setdefault("daily_time", "08:00")
        task.setdefault("weekly_day", 0)
        task.setdefault("custom_interval_value", 15)
        task.setdefault("custom_interval_unit", "minutes")
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

        # Cross-process execution authority.
        task.setdefault("lease_owner", "")
        task.setdefault("lease_until", "")
        task.setdefault("attempt_id", "")
        task.setdefault("attempt_started_at", "")
        task.setdefault("attempt_count", 0)
        task.setdefault("last_attempt_id", "")
        return task

    def list_tasks(self):
        return [self._normalize(item) for item in self._load_all()]

    def get(self, task_id):
        for task in self.list_tasks():
            if task["id"] == task_id:
                return task
        raise KeyError(task_id)

    def upsert(self, task):
        with self._exclusive_lock():
            tasks = [self._normalize(item) for item in self._load_all()]
            raw_item = dict(task)
            item = self._normalize(raw_item)
            existing = next(
                (i for i, current in enumerate(tasks) if current["id"] == item["id"]),
                None,
            )

            if existing is not None:
                current = tasks[existing]
                for field in (
                    "lease_owner",
                    "lease_until",
                    "attempt_id",
                    "attempt_started_at",
                    "attempt_count",
                    "last_attempt_id",
                ):
                    if field not in raw_item:
                        item[field] = current.get(field, item.get(field))

            if not item.get("next_run_at"):
                item["next_run_at"] = compute_next_run(item).isoformat(
                    timespec="seconds"
                )

            if existing is None:
                tasks.append(item)
            else:
                tasks[existing] = item

            self._save_all(tasks)
            return dict(item)

    def delete(self, task_id):
        with self._exclusive_lock():
            tasks = [
                self._normalize(task)
                for task in self._load_all()
                if str(task.get("id") or "") != str(task_id)
            ]
            self._save_all(tasks)

    def due_tasks(self, now=None):
        now = now or datetime.now()
        due = []
        for task in self.list_tasks():
            if not task.get("enabled", True):
                continue

            lease_until = _parse_iso(task.get("lease_until"))
            if lease_until is not None and lease_until > now:
                continue

            next_run = _parse_iso(task.get("next_run_at"))
            if next_run is None:
                task["next_run_at"] = compute_next_run(task, now).isoformat(
                    timespec="seconds"
                )
                self.upsert(task)
                continue
            if next_run <= now:
                due.append(task)

        return sorted(due, key=lambda task: task.get("next_run_at", ""))

    def claim_task(
        self,
        *,
        owner_id,
        task_id="",
        now=None,
        lease_seconds=3600,
        force=False,
    ):
        owner_id = str(owner_id or "").strip()
        if not owner_id:
            raise ValueError("owner_id is required")

        now = now or datetime.now()
        lease_seconds = max(60, int(lease_seconds or 3600))

        with self._exclusive_lock():
            tasks = [self._normalize(item) for item in self._load_all()]
            candidates = []

            for index, task in enumerate(tasks):
                if task_id and task["id"] != task_id:
                    continue
                if not task.get("enabled", True):
                    continue

                lease_until = _parse_iso(task.get("lease_until"))
                if lease_until is not None and lease_until > now:
                    continue

                next_run = _parse_iso(task.get("next_run_at"))
                if not force:
                    if next_run is None or next_run > now:
                        continue

                candidates.append((index, task))

            if not candidates:
                return None

            candidates.sort(key=lambda item: item[1].get("next_run_at", ""))
            index, task = candidates[0]

            attempt_id = uuid.uuid4().hex
            task["lease_owner"] = owner_id
            task["lease_until"] = (
                now + timedelta(seconds=lease_seconds)
            ).isoformat(timespec="seconds")
            task["attempt_id"] = attempt_id
            task["attempt_started_at"] = now.isoformat(timespec="seconds")
            task["attempt_count"] = int(task.get("attempt_count", 0) or 0) + 1
            task["last_status"] = "running"
            task["last_error"] = ""

            tasks[index] = task
            self._save_all(tasks)
            return dict(task)

    def validate_claim(self, task_id, *, attempt_id, owner_id):
        with self._exclusive_lock():
            tasks = [self._normalize(item) for item in self._load_all()]
            task = next(
                (item for item in tasks if item["id"] == task_id),
                None,
            )
            if task is None:
                raise KeyError(task_id)

            if str(task.get("attempt_id") or "") != str(attempt_id or ""):
                raise RuntimeError(
                    "stale scheduler attempt cannot mutate scheduled output"
                )
            if str(task.get("lease_owner") or "") != str(owner_id or ""):
                raise RuntimeError(
                    "scheduler lease is owned by another runner"
                )
            return dict(task)

    def mark_result(
        self,
        task_id,
        status,
        error="",
        chat_id="",
        *,
        attempt_id="",
        owner_id="",
        now=None,
    ):
        now = now or datetime.now()

        with self._exclusive_lock():
            tasks = [self._normalize(item) for item in self._load_all()]
            index = next(
                (i for i, task in enumerate(tasks) if task["id"] == task_id),
                None,
            )
            if index is None:
                raise KeyError(task_id)

            task = tasks[index]
            active_attempt = str(task.get("attempt_id") or "")
            active_owner = str(task.get("lease_owner") or "")

            if active_attempt and not attempt_id:
                raise RuntimeError(
                    "attempt_id is required to complete an active scheduler lease"
                )
            if active_owner and not owner_id:
                raise RuntimeError(
                    "owner_id is required to complete an active scheduler lease"
                )
            if attempt_id and active_attempt != str(attempt_id):
                raise RuntimeError("stale scheduler attempt cannot record a result")
            if owner_id and active_owner != str(owner_id):
                raise RuntimeError("scheduler lease is owned by another runner")

            if active_attempt:
                task["last_attempt_id"] = active_attempt
            task["last_run_at"] = now.isoformat(timespec="seconds")
            task["last_status"] = status
            task["last_error"] = str(error or "")
            if chat_id:
                task["chat_id"] = chat_id
            task["next_run_at"] = compute_next_run(task, now).isoformat(
                timespec="seconds"
            )

            task["lease_owner"] = ""
            task["lease_until"] = ""
            task["attempt_id"] = ""
            task["attempt_started_at"] = ""

            tasks[index] = task
            self._save_all(tasks)
            return dict(task)
