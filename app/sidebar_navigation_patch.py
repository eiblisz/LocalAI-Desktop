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
        new_chat.clicked.connect(self._new_chat)
        layout.addWidget(new_chat)

        self.schedule_button = QPushButton("SCHEDULE")
        self.schedule_button.setObjectName("toolButton")
        self.schedule_button.clicked.connect(self._open_scheduler)
        layout.addWidget(self.schedule_button)

        # Navigation destinations whose dedicated views are separate future slices.
        self.sidebar_navigation_buttons = {}
        for text in ["PROJECTS", "BROWSER", "MEMORY", "SETTINGS"]:
            button = QPushButton(text)
            button.setObjectName("subtleButton")
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

        # Closed chats remain persisted and recoverable through storage APIs, but are
        # intentionally not a separate visible sidebar section. Scheduler histories
        # likewise remain persisted and are represented by the SCHEDULES section.
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

    MainWindow._build_sidebar = _build_sidebar
    MainWindow._load_chat_list = _load_chat_list
    MainWindow._sidebar_navigation_patch_installed = True
