import inspect

from app.main_window import MainWindow
from app.sidebar_navigation_patch import _is_schedule_chat, _open_schedule_history


class _SchedulerStore:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self):
        return list(self._tasks)

    def get(self, task_id):
        for task in self._tasks:
            if task.get("id") == task_id:
                return task
        raise KeyError(task_id)


class _ChatStore:
    def __init__(self, chats):
        self._chats = chats
        self.saved = False

    def load(self, chat_id):
        return dict(self._chats[chat_id])

    def save(self, _chat):
        self.saved = True


class _Window:
    def __init__(self, tasks, chats=None):
        self.scheduler_store = _SchedulerStore(tasks)
        self.store = _ChatStore(chats or {})
        self.current_chat = None
        self.rendered = False
        self.reloaded = False

    def _render_chat(self):
        self.rendered = True

    def _load_chat_list(self):
        self.reloaded = True


def test_sidebar_has_navigation_then_distinct_schedule_and_chat_sections():
    source = inspect.getsource(MainWindow._build_sidebar)

    assert 'QPushButton("+  NEW CHAT")' in source
    assert 'self.schedule_button = QPushButton("SCHEDULE")' in source
    assert '["PROJECTS", "BROWSER", "MEMORY", "EXTENSIONS", "SETTINGS"]' in source
    assert 'button.clicked.connect(self._open_market_browser)' in source
    assert 'button.clicked.connect(self._open_extensions)' in source
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


def test_schedule_rows_are_clickable_and_two_pixels_larger():
    source = inspect.getsource(MainWindow._refresh_schedule_task_labels)

    assert 'QPushButton(f"{dot}  {name}{suffix}")' in source
    assert "font-size:13px" in source
    assert "_open_schedule_history" in source


def test_schedule_click_opens_existing_history_without_mutating_storage():
    window = _Window(
        [{"id": "task-1", "chat_id": "schedule-chat-1"}],
        {"schedule-chat-1": {"id": "schedule-chat-1", "title": "[SCHEDULE] Ido teszt"}},
    )

    _open_schedule_history(window, "task-1")

    assert window.current_chat["id"] == "schedule-chat-1"
    assert window.rendered
    assert window.reloaded
    assert not window.store.saved


def test_schedule_click_without_history_is_fail_closed_and_creates_nothing():
    window = _Window([{"id": "task-1", "chat_id": ""}])

    _open_schedule_history(window, "task-1")

    assert window.current_chat is None
    assert not window.rendered
    assert not window.store.saved


def test_existing_scheduler_completion_still_persists_and_does_not_steal_chat():
    source = inspect.getsource(MainWindow._scheduled_task_finished)

    assert "self.scheduler_runtime.complete(" in source
    assert "current_id == scheduled_chat_id" in source
    assert "_load_chat_list()" in source


def test_browser_sidebar_opens_tradingview_inside_workspace():
    source = inspect.getsource(MainWindow._build_sidebar)
    open_source = inspect.getsource(MainWindow._open_market_browser)

    assert 'if text == "BROWSER"' in source
    assert 'button.setEnabled(True)' in source
    assert 'button.clicked.connect(self._open_market_browser)' in source
    assert "self._open_resource(self._tradingview_workspace_url())" in open_source


def test_sidebar_primary_and_navigation_buttons_share_compact_height():
    source = inspect.getsource(MainWindow._build_sidebar)

    assert 'new_chat.setFixedHeight(34)' in source
    assert 'self.schedule_button.setFixedHeight(34)' in source
    assert 'button.setFixedHeight(34)' in source


def test_sidebar_controls_and_chat_list_share_side_menu_geometry():
    source = inspect.getsource(MainWindow._build_sidebar)

    assert 'new_chat.setObjectName("sideMenuButton")' in source
    assert 'self.schedule_button.setObjectName("sideMenuButton")' in source
    assert 'button.setObjectName("sideMenuButton")' in source
    assert 'self.chat_list.setObjectName("sideChatList")' in source
    assert "ScrollBarAlwaysOff" in source


def test_memory_navigation_is_enabled_and_opens_canonical_dialog():
    source = inspect.getsource(MainWindow._build_sidebar)

    assert 'elif text == "MEMORY":' in source
    assert 'button.clicked.connect(self._open_memory)' in source
    assert '"Review, revise, pin, archive and delete persistent memories."' in source
