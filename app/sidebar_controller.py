from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .ui_theme import COLORS, schedule_status_color


def scheduled_chat_ids(window):
    ids = set()
    try:
        tasks = window.scheduler_store.list_tasks()
    except Exception:
        tasks = []
    for task in tasks:
        chat_id = str(task.get("chat_id", "") or "").strip()
        if chat_id:
            ids.add(chat_id)
    return ids


def is_schedule_chat(window, chat):
    chat_id = str(chat.get("id", "") or "")
    title = str(chat.get("title", "") or "")
    return chat_id in scheduled_chat_ids(window) or title.startswith("[SCHEDULE]")


def open_schedule_history(window, task_id):
    """Open existing schedule history without creating or mutating data."""
    try:
        task = window.scheduler_store.get(task_id)
    except Exception:
        return

    chat_id = str(task.get("chat_id", "") or "").strip()
    if not chat_id:
        return

    try:
        chat = window.store.load(chat_id)
    except Exception:
        return

    window.current_chat = chat
    window._render_chat()
    window._load_chat_list()


class SidebarController:
    """Canonical sidebar presentation controller."""

    def __init__(self, window):
        self.window = window

    def build_sidebar(self):
        window = self.window
        frame = QFrame()
        frame.setObjectName("sidebar")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(6)

        new_chat = QPushButton("+  NEW CHAT")
        new_chat.setObjectName("sideMenuButton")
        new_chat.setFixedHeight(34)
        new_chat.clicked.connect(window._new_chat)
        layout.addWidget(new_chat)

        window.schedule_button = QPushButton("SCHEDULE")
        window.schedule_button.setObjectName("sideMenuButton")
        window.schedule_button.setFixedHeight(34)
        window.schedule_button.clicked.connect(window._open_scheduler)
        layout.addWidget(window.schedule_button)

        window.sidebar_navigation_buttons = {}
        for text in ["PROJECTS", "BROWSER", "MEMORY", "EXTENSIONS", "SETTINGS"]:
            button = QPushButton(text)
            button.setObjectName("sideMenuButton")
            button.setFixedHeight(34)
            if text == "BROWSER":
                button.setEnabled(True)
                button.setToolTip(
                    "Open the TradingView market workspace inside LocalAI Desktop."
                )
                button.clicked.connect(window._open_market_browser)
            elif text == "MEMORY":
                button.setEnabled(True)
                button.setToolTip(
                    "Review, revise, pin, archive and delete persistent memories."
                )
                button.clicked.connect(window._open_memory)
            elif text == "EXTENSIONS":
                button.setEnabled(True)
                button.setToolTip(
                    "Manage saved extension endpoints, capabilities and connection state."
                )
                button.clicked.connect(window._open_extensions)
            else:
                button.setEnabled(False)
                button.setToolTip(f"{text.title()} view is not implemented yet.")
            window.sidebar_navigation_buttons[text] = button
            layout.addWidget(button)

        layout.addSpacing(8)
        schedules_label = QLabel("SCHEDULES")
        schedules_label.setObjectName("muted")
        layout.addWidget(schedules_label)

        window.schedule_task_status_layout = QVBoxLayout()
        window.schedule_task_status_layout.setContentsMargins(6, 0, 4, 0)
        window.schedule_task_status_layout.setSpacing(1)
        layout.addLayout(window.schedule_task_status_layout)

        layout.addSpacing(10)
        chats_label = QLabel("CHATS")
        chats_label.setObjectName("muted")
        layout.addWidget(chats_label)

        window.chat_list = QListWidget()
        window.chat_list.setObjectName("sideChatList")
        window.chat_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        window.chat_list.itemClicked.connect(window._chat_selected)
        window.chat_list.itemDoubleClicked.connect(window._rename_chat_item)
        window.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        window.chat_list.customContextMenuRequested.connect(
            window._chat_context_menu
        )
        layout.addWidget(window.chat_list, 1)

        note = QLabel("Right-click a chat to rename, pin or close it.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        return frame

    def load_chat_list(self):
        window = self.window
        selected_id = window.current_chat.get("id") if window.current_chat else None
        all_chats = window.store.list_chats(include_closed=True)
        chats = [
            chat
            for chat in all_chats
            if not bool(chat.get("closed", False))
            and not is_schedule_chat(window, chat)
        ]

        window.chat_list.clear()
        selected_row = -1
        for row, chat in enumerate(chats):
            title = chat.get("title", "New chat")
            if chat.get("pinned", False):
                title = f"[PIN] {title}"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, chat["id"])
            item.setToolTip("Right-click for chat actions")
            window.chat_list.addItem(item)
            if chat["id"] == selected_id:
                selected_row = row

        if selected_row >= 0:
            window.chat_list.setCurrentRow(selected_row)

    def refresh_schedule_task_labels(self):
        window = self.window
        if not hasattr(window, "schedule_task_status_layout"):
            return

        window._clear_schedule_task_labels()
        tasks = window.scheduler_store.list_tasks()
        running_id = ""
        if window.scheduled_worker is not None:
            running_id = str(
                getattr(window.scheduled_worker, "task", {}).get("id", "")
            )

        for task in tasks:
            enabled = bool(task.get("enabled", True))
            failed = task.get("last_status") == "failed"
            running = (
                task.get("id") == running_id
                or window.scheduler_store.is_leased(task)
            )
            pulse = window.schedule_pulse_on

            if failed and enabled:
                dot = "●"
                color = schedule_status_color("failed", pulse=pulse)
                suffix = "  ERROR"
            elif running:
                dot = "●"
                color = schedule_status_color("running", pulse=pulse)
                suffix = "  RUNNING"
            elif enabled:
                dot = "●"
                color = schedule_status_color("enabled", pulse=pulse)
                suffix = ""
            else:
                dot = "○"
                color = schedule_status_color("disabled")
                suffix = "  DISABLED"

            name = str(task.get("name", "Scheduled task")).strip() or "Scheduled task"
            task_id = str(task.get("id", "") or "")
            button = QPushButton(f"{dot}  {name}{suffix}")
            button.setObjectName("scheduleHistoryButton")
            button.setStyleSheet(
                "QPushButton {"
                "background:transparent;border:none;border-radius:6px;"
                f"padding:3px 4px 3px 8px;color:{color};font-size:13px;"
                "text-align:left;"
                "}"
                f"QPushButton:hover {{background:{COLORS.panel_hover};"
                f"color:{COLORS.text_bright};}}"
            )
            button.setToolTip(
                "Open this schedule's saved output/history.\n"
                "Type: {task_type}\nNext run: {next_run}\nLast status: {last_status}".format(
                    task_type=task.get("task_type", "custom"),
                    next_run=task.get("next_run_at") or "not scheduled",
                    last_status=task.get("last_status", "never"),
                )
            )
            button.clicked.connect(
                lambda _checked=False, selected_task_id=task_id: open_schedule_history(
                    window, selected_task_id
                )
            )
            window.schedule_task_status_layout.addWidget(button)
