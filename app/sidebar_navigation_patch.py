"""Presentation-only sidebar separation for schedules and normal chats.

This patch deliberately leaves scheduler execution/storage and chat persistence unchanged.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QFrame


def _scheduled_chat_ids(window):
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


def _is_schedule_chat(window, chat):
    chat_id = str(chat.get("id", "") or "")
    title = str(chat.get("title", "") or "")
    return chat_id in _scheduled_chat_ids(window) or title.startswith("[SCHEDULE]")


def _open_schedule_history(window, task_id):
    """Open an existing schedule history without creating or mutating data."""
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


def install_sidebar_navigation_patch(main_window_module):
    MainWindow = main_window_module.MainWindow
    if getattr(MainWindow, "_sidebar_navigation_patch_installed", False):
        return

    def _build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(6)

        new_chat = QPushButton("+  NEW CHAT")
        new_chat.setObjectName("sideMenuButton")
        new_chat.setFixedHeight(34)
        new_chat.clicked.connect(self._new_chat)
        layout.addWidget(new_chat)

        self.schedule_button = QPushButton("SCHEDULE")
        self.schedule_button.setObjectName("sideMenuButton")
        self.schedule_button.setFixedHeight(34)
        self.schedule_button.clicked.connect(self._open_scheduler)
        layout.addWidget(self.schedule_button)

        self.sidebar_navigation_buttons = {}
        for text in ["PROJECTS", "BROWSER", "MEMORY", "EXTENSIONS", "SETTINGS"]:
            button = QPushButton(text)
            button.setObjectName("sideMenuButton")
            button.setFixedHeight(34)
            if text == "BROWSER":
                button.setEnabled(True)
                button.setToolTip(
                    "Open the TradingView market workspace inside LocalAI Desktop."
                )
                button.clicked.connect(self._open_market_browser)
            elif text == "EXTENSIONS":
                button.setEnabled(True)
                button.setToolTip(
                    "Manage saved extension endpoints, capabilities and connection state."
                )
                button.clicked.connect(self._open_extensions)
            else:
                button.setEnabled(False)
                button.setToolTip(f"{text.title()} view is not implemented yet.")
            self.sidebar_navigation_buttons[text] = button
            layout.addWidget(button)

        layout.addSpacing(8)
        schedules_label = QLabel("SCHEDULES")
        schedules_label.setObjectName("muted")
        layout.addWidget(schedules_label)

        self.schedule_task_status_layout = QVBoxLayout()
        self.schedule_task_status_layout.setContentsMargins(6, 0, 4, 0)
        self.schedule_task_status_layout.setSpacing(1)
        layout.addLayout(self.schedule_task_status_layout)

        layout.addSpacing(10)
        chats_label = QLabel("CHATS")
        chats_label.setObjectName("muted")
        layout.addWidget(chats_label)

        self.chat_list = QListWidget()
        self.chat_list.setObjectName("sideChatList")
        self.chat_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chat_list.itemClicked.connect(self._chat_selected)
        self.chat_list.itemDoubleClicked.connect(self._rename_chat_item)
        self.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._chat_context_menu)
        layout.addWidget(self.chat_list, 1)

        note = QLabel("Right-click a chat to rename, pin or close it.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        return frame

    def _load_chat_list(self):
        selected_id = self.current_chat.get("id") if self.current_chat else None
        all_chats = self.store.list_chats(include_closed=True)
        chats = [
            chat
            for chat in all_chats
            if not bool(chat.get("closed", False)) and not _is_schedule_chat(self, chat)
        ]

        self.chat_list.clear()
        selected_row = -1
        for row, chat in enumerate(chats):
            title = chat.get("title", "New chat")
            if chat.get("pinned", False):
                title = f"[PIN] {title}"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, chat["id"])
            item.setToolTip("Right-click for chat actions")
            self.chat_list.addItem(item)
            if chat["id"] == selected_id:
                selected_row = row

        if selected_row >= 0:
            self.chat_list.setCurrentRow(selected_row)

    def _refresh_schedule_task_labels(self):
        if not hasattr(self, "schedule_task_status_layout"):
            return

        self._clear_schedule_task_labels()
        tasks = self.scheduler_store.list_tasks()
        running_id = ""
        if self.scheduled_worker is not None:
            running_id = str(getattr(self.scheduled_worker, "task", {}).get("id", ""))

        for task in tasks:
            enabled = bool(task.get("enabled", True))
            failed = task.get("last_status") == "failed"
            running = task.get("id") == running_id
            pulse = self.schedule_pulse_on

            if failed and enabled:
                dot = "●"
                color = "#E07A82" if pulse else "#B95A63"
                suffix = "  ERROR"
            elif running:
                dot = "●"
                color = "#8AC89C" if pulse else "#5FAE78"
                suffix = "  RUNNING"
            elif enabled:
                dot = "●"
                color = "#86C69A" if pulse else "#65A97A"
                suffix = ""
            else:
                dot = "○"
                color = "#7F8995"
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
                "QPushButton:hover {background:#1D2630;color:#FFFFFF;}"
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
                lambda _checked=False, selected_task_id=task_id: _open_schedule_history(
                    self, selected_task_id
                )
            )
            self.schedule_task_status_layout.addWidget(button)

    MainWindow._build_sidebar = _build_sidebar
    MainWindow._load_chat_list = _load_chat_list
    MainWindow._refresh_schedule_task_labels = _refresh_schedule_task_labels
    MainWindow._sidebar_navigation_patch_installed = True
