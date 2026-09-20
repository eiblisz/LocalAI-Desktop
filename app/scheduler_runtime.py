from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScheduledCompletion:
    task: dict
    chat: dict


class SchedulerRuntime:
    """
    Host-owned scheduler persistence/runtime boundary.

    Qt timers, threads and presentation remain in MainWindow. This component
    owns scheduler task lookup, due selection and durable result persistence.
    """

    def __init__(self, scheduler_store, chat_store, *, now_provider=None):
        self.scheduler_store = scheduler_store
        self.chat_store = chat_store
        self._now_provider = now_provider or datetime.now

    def next_due_task_id(self):
        due = self.scheduler_store.due_tasks(self._now_provider())
        if not due:
            return ""
        return str(due[0].get("id") or "")

    def claim_task(
        self,
        task_id="",
        *,
        owner_id,
        force=False,
        lease_seconds=3600,
    ):
        return self.scheduler_store.claim_task(
            owner_id=owner_id,
            task_id=task_id,
            now=self._now_provider(),
            lease_seconds=lease_seconds,
            force=force,
        )

    def get_task(self, task_id):
        return self.scheduler_store.get(task_id)

    def ensure_schedule_chat(self, task):
        chat_id = str(task.get("chat_id") or "").strip()
        if chat_id:
            try:
                return self.chat_store.load(chat_id)
            except Exception:
                pass

        chat = self.chat_store.new_chat(task.get("model", ""))
        chat["title"] = (
            f'[SCHEDULE] {task.get("name", "Scheduled task")}'[:80]
        )
        chat["model"] = task.get("model", "")
        self.chat_store.save(chat)
        return chat

    def complete(
        self,
        task_id,
        content,
        *,
        attempt_id="",
        owner_id="",
    ):
        task = self.get_task(task_id)
        chat = self.ensure_schedule_chat(task)
        stamp = self._now_provider().strftime("%Y-%m-%d %H:%M")
        chat["messages"].append(
            {
                "role": "assistant",
                "content": (
                    f"## Scheduled run - {stamp}\n\n"
                    f"**Task:** {task.get('name', 'Scheduled task')}\n\n"
                    f"{content}"
                ),
            }
        )
        self.chat_store.save(chat)
        updated = self.scheduler_store.mark_result(
            task_id,
            status="success",
            chat_id=chat["id"],
            attempt_id=attempt_id,
            owner_id=owner_id,
            now=self._now_provider(),
        )
        return ScheduledCompletion(task=updated, chat=chat)

    def fail(
        self,
        task_id,
        message,
        *,
        attempt_id="",
        owner_id="",
    ):
        return self.scheduler_store.mark_result(
            task_id,
            status="failed",
            error=message,
            attempt_id=attempt_id,
            owner_id=owner_id,
            now=self._now_provider(),
        )
