import json
import os
import uuid

import psutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import RUNTIME_DIR


OWNER_LOCALAI_DESKTOP = "LOCALAI_DESKTOP"
OWNER_EINSTEIN = "EINSTEIN"
OWNER_MANUAL = "MANUAL"
OWNER_SCHEDULER = "SCHEDULER"
OWNER_OTHER = "OTHER"
OWNER_UNKNOWN = "UNKNOWN"

ALLOWED_OWNERS = {
    OWNER_LOCALAI_DESKTOP,
    OWNER_EINSTEIN,
    OWNER_MANUAL,
    OWNER_SCHEDULER,
    OWNER_OTHER,
    OWNER_UNKNOWN,
}

STATE_IDLE = "IDLE"
STATE_RESERVED = "RESERVED"
STATE_MODEL_LOADING = "MODEL_LOADING"
STATE_INFERENCE_ACTIVE = "INFERENCE_ACTIVE"
STATE_RELEASING = "RELEASING"
STATE_STALE = "STALE"
STATE_ERROR = "ERROR"

ALLOWED_STATES = {
    STATE_IDLE,
    STATE_RESERVED,
    STATE_MODEL_LOADING,
    STATE_INFERENCE_ACTIVE,
    STATE_RELEASING,
    STATE_STALE,
    STATE_ERROR,
}

RESOURCE_LEASE_ENV_VAR = "LOCALAI_OLLAMA_RESOURCE_LEASE_PATH"


def default_lease_path(env=None):
    env = os.environ if env is None else env
    override = str(env.get(RESOURCE_LEASE_ENV_VAR, "") or "").strip()
    if override:
        return Path(os.path.expandvars(override)).expanduser()
    return RUNTIME_DIR / "ollama_resource_leases.json"


DEFAULT_LEASE_PATH = default_lease_path()


class OllamaResourceBusyError(RuntimeError):
    pass


class ResourceLeaseStore:
    """Cross-process ownership ledger for the shared local Ollama runtime."""

    def __init__(self, path: Path = DEFAULT_LEASE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @staticmethod
    def _now():
        return datetime.now().isoformat(timespec="seconds")

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

    def _save_all(self, items):
        temp = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp.write_text(
                json.dumps(items, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _normalize(item):
        item = dict(item or {})
        item.setdefault("lease_id", uuid.uuid4().hex)
        item.setdefault("owner", OWNER_UNKNOWN)
        item.setdefault("owner_id", "")
        item.setdefault("model", "")
        item.setdefault("owner_pid", None)
        item.setdefault("model_pid", None)
        item.setdefault("request_id", "")
        item.setdefault("start_time", "")
        item.setdefault("last_heartbeat", "")
        item.setdefault("state", STATE_IDLE)
        item.setdefault("detail", "")
        if item["owner"] not in ALLOWED_OWNERS:
            item["owner"] = OWNER_UNKNOWN
        if item["state"] not in ALLOWED_STATES:
            item["state"] = STATE_ERROR
        return item

    def list_leases(self):
        with self._exclusive_lock():
            items = [self._normalize(item) for item in self._load_all()]
            changed = False
            now = self._now()
            for item in items:
                pid = item.get("owner_pid")
                if (
                    isinstance(pid, int)
                    and pid > 0
                    and item.get("state") != STATE_STALE
                    and not psutil.pid_exists(pid)
                ):
                    item["state"] = STATE_STALE
                    item["last_heartbeat"] = now
                    item["detail"] = "owner process no longer exists"
                    changed = True
            if changed:
                self._save_all(items)
            return items

    def leases_for_model(self, model):
        model = str(model or "").strip()
        return [
            item
            for item in self.list_leases()
            if str(item.get("model") or "").strip() == model
        ]

    def upsert(
        self,
        *,
        owner,
        owner_id,
        model,
        state,
        owner_pid=None,
        model_pid=None,
        request_id="",
        detail="",
    ):
        owner = str(owner or OWNER_UNKNOWN).strip().upper()
        state = str(state or STATE_ERROR).strip().upper()
        if owner not in ALLOWED_OWNERS:
            raise ValueError(f"invalid owner: {owner}")
        if state not in ALLOWED_STATES:
            raise ValueError(f"invalid state: {state}")

        owner_id = str(owner_id or "").strip()
        model = str(model or "").strip()
        if not owner_id:
            raise ValueError("owner_id is required")
        if not model:
            raise ValueError("model is required")

        now = self._now()
        with self._exclusive_lock():
            items = [self._normalize(item) for item in self._load_all()]
            index = next(
                (
                    i
                    for i, item in enumerate(items)
                    if item.get("owner") == owner
                    and item.get("owner_id") == owner_id
                    and item.get("model") == model
                ),
                None,
            )
            if index is None:
                item = self._normalize(
                    {
                        "owner": owner,
                        "owner_id": owner_id,
                        "model": model,
                        "start_time": now,
                    }
                )
                items.append(item)
                index = len(items) - 1
            else:
                item = items[index]
                if not item.get("start_time"):
                    item["start_time"] = now

            item["state"] = state
            item["last_heartbeat"] = now
            item["owner_pid"] = (
                int(owner_pid) if owner_pid not in {None, ""} else item.get("owner_pid")
            )
            if model_pid is not None:
                item["model_pid"] = int(model_pid) if str(model_pid).isdigit() else None
            if request_id:
                item["request_id"] = str(request_id)
            item["detail"] = str(detail or "")
            items[index] = item
            self._save_all(items)
            return dict(item)

    def heartbeat(
        self,
        *,
        owner,
        owner_id,
        model,
        state=None,
        model_pid=None,
        request_id="",
        detail="",
    ):
        current = self.find_owned(owner=owner, owner_id=owner_id, model=model)
        return self.upsert(
            owner=owner,
            owner_id=owner_id,
            model=model,
            state=state or (current or {}).get("state", STATE_IDLE),
            owner_pid=(current or {}).get("owner_pid"),
            model_pid=(
                model_pid
                if model_pid is not None
                else (current or {}).get("model_pid")
            ),
            request_id=request_id or (current or {}).get("request_id", ""),
            detail=detail,
        )

    def find_owned(self, *, owner, owner_id, model):
        owner = str(owner or "").strip().upper()
        owner_id = str(owner_id or "").strip()
        model = str(model or "").strip()
        matches = [
            item
            for item in self.leases_for_model(model)
            if item.get("owner") == owner and item.get("owner_id") == owner_id
        ]
        if not matches:
            return None
        return sorted(
            matches,
            key=lambda item: item.get("last_heartbeat", ""),
            reverse=True,
        )[0]

    def ownership(self, model):
        all_leases = self.leases_for_model(model)
        leases = [
            item
            for item in all_leases
            if item.get("state") != STATE_STALE
        ]
        if not leases:
            stale = [
                item for item in all_leases
                if item.get("state") == STATE_STALE
            ]
            if stale:
                latest = dict(
                    sorted(
                        stale,
                        key=lambda item: item.get("last_heartbeat", ""),
                        reverse=True,
                    )[0]
                )
                latest["owner"] = OWNER_UNKNOWN
                latest["owner_id"] = ""
                latest["model_pid"] = None
                return latest
            return {
                "owner": OWNER_UNKNOWN,
                "owner_id": "",
                "model": str(model or ""),
                "state": STATE_IDLE,
                "model_pid": None,
            }
        owners = {
            (item.get("owner"), item.get("owner_id"))
            for item in leases
        }
        if len(owners) != 1:
            return {
                "owner": OWNER_UNKNOWN,
                "owner_id": "",
                "model": str(model or ""),
                "state": STATE_ERROR,
                "model_pid": None,
                "detail": "multiple active ownership claims",
            }
        return sorted(
            leases,
            key=lambda item: item.get("last_heartbeat", ""),
            reverse=True,
        )[0]

    def can_control_model(self, *, owner, owner_id, model, allow_active=False):
        owner = str(owner or "").strip().upper()
        owner_id = str(owner_id or "").strip()
        model = str(model or "").strip()
        leases = self.leases_for_model(model)
        lease = next(
            (
                item
                for item in leases
                if item.get("owner") == owner
                and item.get("owner_id") == owner_id
            ),
            None,
        )
        if lease is None:
            return False, self.ownership(model)
        if lease.get("state") == STATE_STALE:
            return False, lease

        foreign = [
            item
            for item in leases
            if item.get("state") != STATE_STALE
            and not (
                item.get("owner") == owner
                and item.get("owner_id") == owner_id
            )
        ]
        if foreign:
            return False, self.ownership(model)

        if lease.get("state") == STATE_INFERENCE_ACTIVE and not allow_active:
            return False, lease
        return True, lease

    def foreign_active_leases(self, *, owner, owner_id):
        blocking_states = {
            STATE_RESERVED,
            STATE_MODEL_LOADING,
            STATE_INFERENCE_ACTIVE,
            STATE_RELEASING,
        }
        return [
            item
            for item in self.list_leases()
            if item.get("state") in blocking_states
            and not (
                item.get("owner") == owner
                and item.get("owner_id") == owner_id
            )
        ]

    def mark_stale(self, model, detail="runtime reconciliation"):
        model = str(model or "").strip()
        now = self._now()
        with self._exclusive_lock():
            items = [self._normalize(item) for item in self._load_all()]
            changed = []
            for item in items:
                if item.get("model") != model:
                    continue
                item["state"] = STATE_STALE
                item["last_heartbeat"] = now
                item["detail"] = str(detail or "")
                changed.append(dict(item))
            self._save_all(items)
            return changed
