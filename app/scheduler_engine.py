import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime

from .ollama_client import OllamaClient
from .scheduled_task_executor import ScheduledTaskExecutor
from .scheduler_runtime import SchedulerRuntime
from .scheduler_store import ScheduledTaskStore
from .storage import ChatStore


@dataclass(frozen=True)
class SchedulerEngineResult:
    status: str
    task_id: str = ""
    attempt_id: str = ""
    message: str = ""


class SchedulerEngine:
    """
    UI-independent scheduled-task execution engine.

    The store grants cross-process execution authority through a lease and an
    attempt id. Only the active attempt may persist success/failure.
    """

    def __init__(
        self,
        scheduler_store=None,
        chat_store=None,
        client=None,
        *,
        owner_id=None,
        now_provider=None,
        lease_seconds=3600,
        executor_factory=None,
    ):
        self.scheduler_store = scheduler_store or ScheduledTaskStore()
        self.chat_store = chat_store or ChatStore()
        self.client = client or OllamaClient(auto_prepare_model=True)
        self._now_provider = now_provider or datetime.now
        self.lease_seconds = max(60, int(lease_seconds or 3600))
        self.owner_id = owner_id or self.default_owner_id()
        self.runtime = SchedulerRuntime(
            self.scheduler_store,
            self.chat_store,
            now_provider=self._now_provider,
        )
        self.executor_factory = executor_factory or (
            lambda client: ScheduledTaskExecutor(client)
        )

    @staticmethod
    def default_owner_id():
        return (
            f"runner:{socket.gethostname()}:{os.getpid()}:"
            f"{uuid.uuid4().hex[:8]}"
        )

    def claim_next_due(self):
        return self.runtime.claim_task(
            owner_id=self.owner_id,
            force=False,
            lease_seconds=self.lease_seconds,
        )

    def run_once(self):
        task = self.claim_next_due()
        if task is None:
            return SchedulerEngineResult(status="idle")

        task_id = str(task.get("id") or "")
        attempt_id = str(task.get("attempt_id") or "")

        try:
            result = self.executor_factory(self.client).execute(task)
            completion = self.runtime.complete(
                task_id,
                result.content,
                attempt_id=attempt_id,
                owner_id=self.owner_id,
            )
            return SchedulerEngineResult(
                status="success",
                task_id=task_id,
                attempt_id=attempt_id,
                message=completion.chat.get("title", ""),
            )
        except Exception as exc:
            message = str(exc)
            try:
                self.runtime.fail(
                    task_id,
                    message,
                    attempt_id=attempt_id,
                    owner_id=self.owner_id,
                )
            except RuntimeError:
                # A stale attempt must never overwrite a newer runner's state.
                return SchedulerEngineResult(
                    status="stale",
                    task_id=task_id,
                    attempt_id=attempt_id,
                    message=message,
                )
            return SchedulerEngineResult(
                status="failed",
                task_id=task_id,
                attempt_id=attempt_id,
                message=message,
            )
