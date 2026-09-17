import inspect

from app.main_window import MainWindow
from app.sidebar_navigation_patch import _is_schedule_chat


class _SchedulerStore:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self):
        return list(self._tasks)


class _Window:
    def __init__(self, tasks):
        self.scheduler_store = _SchedulerStore(tasks)


def test_sidebar_has_navigation_then_distinct_schedule_and_chat_sections():
    source = inspect.getsource(MainWindow._build_sidebar)

    assert 'QPushButton("+  NEW CHAT")' in source
    assert 'self.schedule_button = QPushButton("SCHEDULE")' in source
    assert '["PROJECTS", "BROWSER", "MEMORY", "SETTINGS"]' in source
    assert 'QLabel("SCHEDULES")' in source
    assert 'QLabel("CHATS")' in source
    assert source.index('QLabel("SCHEDULES")') < source.index('QLabel("CHATS")')
    assert "schedule_task_status_layout" in source
    assert "CLOSED CHATS" not in source


def test_schedule_chat_is_excluded_by_task_chat_id_or_schedule_title():
    window = _Window([{"id": "task-1", "chat_id": "schedule-chat-1"}])

    assert _is_schedule_chat(window, {"id": "schedule-chat-1", "title": "History"})
    assert _is_schedule_chat(window, {"id": "orphan", "title": "[SCHEDULE] Old task"})
    assert not _is_schedule_chat(window, {"id": "normal-1", "title": "Teaskanna kereses"})


def test_chat_list_filter_is_presentation_only_and_does_not_delete_history():
    source = inspect.getsource(MainWindow._load_chat_list)

    assert "include_closed=True" in source
    assert "_is_schedule_chat(self, chat)" in source
    assert "chat.get(\"closed\", False)" in source
    assert ".delete(" not in source
    assert ".save(" not in source
    assert "scheduler_store.mark_result" not in source


def test_existing_scheduler_completion_still_persists_and_does_not_steal_chat():
    source = inspect.getsource(MainWindow._scheduled_task_finished)

    assert "self.store.save(chat)" in source
    assert "self.scheduler_store.mark_result" in source
    assert "current_id == scheduled_chat_id" in source
    assert "_load_chat_list()" in source
