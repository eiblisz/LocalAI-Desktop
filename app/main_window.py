import html
import webbrowser
from datetime import datetime
from pathlib import Path

import markdown
from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .artifact_utils import (
    artifact_url,
    open_file,
    open_folder,
    path_from_artifact_url,
)
from .config import APP_NAME, DEFAULT_SYSTEM_PROMPT
from .document_tools import (
    build_document_messages,
    build_excel_messages,
    build_summary_messages,
    conversation_text,
    topic_title,
)
from .artifact_themes import document_preset_labels, workbook_preset_labels
from .docx_tool import create_docx
from .excel_tool import create_conversation_excel, create_structured_excel
from .file_reader import read_attachment
from .html_tool import create_html
from .memory_extractor import is_explicit_memory_request
from .memory_store import MemoryStore
from .ollama_client import OllamaClient
from .pdf_tool import create_pdf
from .resource_monitor import format_resource_summary, get_system_metrics
from .scheduler_dialog import SchedulerDialog
from .scheduler_store import ScheduledTaskStore
from .storage import ChatStore
from .workers import (
    ChatWebWorker,
    ChatWorker,
    DocumentWorker,
    MemoryWriteWorker,
    ScheduledTaskWorker,
)


STYLE = """
QMainWindow, QWidget {
    background: #101419;
    color: #EEF1F5;
    font-family: "Segoe UI";
    font-size: 14px;
}
QFrame#topbar, QFrame#sidebar, QFrame#tools {
    background: #141A20;
}
QLabel#brand {
    font-size: 19px;
    font-weight: 700;
}
QLabel#chatTitle {
    font-size: 19px;
    font-weight: 700;
    color: #F4F6F8;
}
QLabel#muted {
    color: #9099A6;
    font-size: 12px;
}
QPushButton {
    background: #202730;
    border: 1px solid #323C48;
    border-radius: 10px;
    padding: 9px 13px;
    color: #F4F6F8;
}
QPushButton:hover {
    background: #29323D;
}
QPushButton#primary {
    background: #C73B49;
    border: 1px solid #D85662;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: #D24A57;
}
QPushButton#toolButton {
    min-height: 44px;
    font-weight: 700;
}
QPushButton#subtleButton {
    background: transparent;
    border: 1px solid #2D3742;
    color: #AAB2BD;
}
QComboBox {
    background: #171D24;
    border: 1px solid #35404C;
    border-radius: 9px;
    padding: 8px 12px;
    min-width: 220px;
}
QComboBox QAbstractItemView {
    background: #171D24;
    selection-background-color: #2A3440;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    background: transparent;
    color: #EEF1F5;
    border-radius: 9px;
    padding: 11px;
    margin: 2px 0;
}
QListWidget::item:hover {
    background: #1D2630;
    color: #FFFFFF;
}
QListWidget::item:selected,
QListWidget::item:selected:active,
QListWidget::item:selected:!active {
    background: #27323E;
    color: #FFFFFF;
}
QTextBrowser {
    background: #0F1318;
    border: none;
    padding: 18px;
    font-size: 16px;
}
QTextEdit {
    background: #161C23;
    border: 1px solid #35404C;
    border-radius: 12px;
    padding: 10px;
    font-size: 14px;
}
QSplitter::handle {
    background: #252D36;
    width: 1px;
}
QMenu {
    background: #1B222A;
    color: #EEF1F5;
    border: 1px solid #35404C;
    padding: 5px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #2A3440;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalAI Desktop")
        self.resize(1420, 900)

        self.client = OllamaClient()
        self.store = ChatStore()
        self.memory_store = MemoryStore()
        self.current_chat = None
        self.attachment_context = []
        self.thread = None
        self.worker = None
        self.partial_assistant = ""
        self.current_chat_uses_web = False
        self.generation_chat_id = ""
        self.show_closed = False
        self.thinking_phase = 0
        self.thinking_base_text = "Gondolkodik"
        self.thinking_timer = QTimer(self)
        self.thinking_timer.setInterval(450)
        self.thinking_timer.timeout.connect(self._pulse_thinking_indicator)
        self.pdf_thread = None
        self.pdf_worker = None
        self.pending_pdf_title = ""
        self.pending_tool = ""
        self.pending_preset = ""
        self.pending_model = ""
        self.pending_source_text = ""
        self.active_tool = "PDF"
        self.last_artifact_path = None
        self.scheduler_store = ScheduledTaskStore()
        self.scheduler_dialog = None
        self.scheduled_thread = None
        self.scheduled_worker = None
        self.pending_scheduled_task_id = ""
        self.schedule_indicator_state = "idle"
        self.schedule_pulse_on = False

        self.setStyleSheet(STYLE)
        self._build_ui()
        self._load_models()
        self._load_chat_list()
        self._ensure_chat()

        self.resource_timer = QTimer(self)
        self.resource_timer.timeout.connect(self._refresh_resources)
        self.resource_timer.start(1000)
        self._refresh_resources()

        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.timeout.connect(self._check_scheduled_tasks)
        self.scheduler_timer.start(30000)

        self.schedule_pulse_timer = QTimer(self)
        self.schedule_pulse_timer.timeout.connect(self._pulse_schedule_button)
        self.schedule_pulse_timer.start(850)

        self._refresh_schedule_indicator()
        QTimer.singleShot(3000, self._check_scheduled_tasks)

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(18, 10, 18, 10)

        brand_box = QVBoxLayout()
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        subtitle = QLabel("Your private local AI assistant")
        subtitle.setObjectName("muted")
        brand_box.addWidget(brand)
        brand_box.addWidget(subtitle)
        top_layout.addLayout(brand_box)

        self.resource_label = QLabel("CPU -- | RAM -- | GPU -- | VRAM --")
        self.resource_label.setObjectName("muted")
        self.resource_label.setMinimumWidth(440)
        self.resource_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self.resource_label, 1)
        top_layout.addStretch()

        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._model_changed)
        top_layout.addWidget(self.model_combo)

        self.status = QLabel("Ollama: checking...")
        self.status.setObjectName("muted")
        self.status.setMinimumWidth(0)
        self.status.setMaximumWidth(360)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        top_layout.addWidget(self.status)

        root.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_chat_panel())
        splitter.addWidget(self._build_tools_panel())
        splitter.setSizes([300, 900, 250])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def _build_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebar")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 16)

        new_chat = QPushButton("+  NEW CHAT")
        new_chat.clicked.connect(self._new_chat)
        layout.addWidget(new_chat)

        self.schedule_button = QPushButton("SCHEDULE")
        self.schedule_button.setObjectName("toolButton")
        self.schedule_button.clicked.connect(self._open_scheduler)
        layout.addWidget(self.schedule_button)

        self.schedule_task_status_layout = QVBoxLayout()
        self.schedule_task_status_layout.setContentsMargins(6, 0, 4, 0)
        self.schedule_task_status_layout.setSpacing(1)
        layout.addLayout(self.schedule_task_status_layout)

        layout.addSpacing(8)

        label = QLabel("Conversations")
        label.setObjectName("muted")
        layout.addWidget(label)

        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self._chat_selected)
        self.chat_list.itemDoubleClicked.connect(self._rename_chat_item)
        self.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._chat_context_menu)
        layout.addWidget(self.chat_list, 1)

        self.closed_button = QPushButton("CLOSED CHATS")
        self.closed_button.setObjectName("subtleButton")
        self.closed_button.clicked.connect(self._toggle_closed_chats)
        layout.addWidget(self.closed_button)

        note = QLabel("Right-click a chat to rename, pin or close it.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        return frame

    def _build_chat_panel(self):
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 10, 18, 4)
        self.chat_title = QLabel("Local AI")
        self.chat_title.setObjectName("chatTitle")
        header_layout.addWidget(self.chat_title)
        header_layout.addStretch()
        layout.addWidget(header)

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenLinks(False)
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setMinimumWidth(0)
        self.chat_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.chat_view.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )
        text_option = self.chat_view.document().defaultTextOption()
        text_option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.chat_view.document().setDefaultTextOption(text_option)
        self.chat_view.anchorClicked.connect(self._open_artifact_link)
        layout.addWidget(self.chat_view, 1)

        self.thinking_label = QLabel("")
        self.thinking_label.setFixedHeight(26)
        self.thinking_label.setContentsMargins(18, 0, 18, 0)
        self.thinking_label.setStyleSheet(
            "color:#7FAE8C;font-size:12px;font-weight:600;"
        )
        layout.addWidget(self.thinking_label)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(12, 10, 12, 12)

        attach = QPushButton("Attach")
        attach.clicked.connect(self._attach_file)
        input_row.addWidget(attach)

        self.web_button = QPushButton("WEB AUTO")
        self.web_button.setCheckable(True)
        self.web_button.setToolTip(
            "WEB AUTO searches only when the message clearly asks for current web information. "
            "Toggle to WEB ON to force read-only web research."
        )
        self.web_button.toggled.connect(self._web_button_toggled)
        input_row.addWidget(self.web_button)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Write a message...")
        self.input.setFixedHeight(82)
        input_row.addWidget(self.input, 1)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_generation)
        input_row.addWidget(self.stop_button)

        send = QPushButton("Send")
        send.setObjectName("primary")
        send.clicked.connect(self._send)
        input_row.addWidget(send)

        layout.addLayout(input_row)
        return frame

    def _build_tools_panel(self):
        frame = QFrame()
        frame.setObjectName("tools")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 18, 16, 18)

        title = QLabel("TOOLS")
        title.setObjectName("brand")
        layout.addWidget(title)

        self.tool_buttons = {}
        for text in ["PDF", "DOCX", "EXCEL", "HTML", "SUMMARY"]:
            button = QPushButton(text)
            button.setObjectName("toolButton")
            button.clicked.connect(
                lambda _checked=False, name=text: self._select_tool(name)
            )
            self.tool_buttons[text] = button
            layout.addWidget(button)

        layout.addSpacing(10)
        self.tool_options_label = QLabel("PDF OPTIONS")
        self.tool_options_label.setObjectName("muted")
        layout.addWidget(self.tool_options_label)

        self.preset_label = QLabel("Preset")
        self.preset_label.setObjectName("muted")
        layout.addWidget(self.preset_label)

        self.pdf_preset = QComboBox()
        self.pdf_preset.addItems(["Red Professional", "Red Executive"])
        layout.addWidget(self.pdf_preset)

        source_label = QLabel("Source")
        source_label.setObjectName("muted")
        layout.addWidget(source_label)

        self.pdf_source = QComboBox()
        self.pdf_source.addItems(["Current conversation", "Custom topic"])
        self.pdf_source.currentTextChanged.connect(self._pdf_source_changed)
        layout.addWidget(self.pdf_source)

        self.pdf_topic_label = QLabel("Topic / instructions")
        self.pdf_topic_label.setObjectName("muted")
        self.pdf_topic_label.hide()
        layout.addWidget(self.pdf_topic_label)

        self.pdf_topic = QTextEdit()
        self.pdf_topic.setPlaceholderText(
            "Example: Create a 3-page overview of local AI assistants, "
            "with benefits, limitations and practical examples."
        )
        self.pdf_topic.setFixedHeight(100)
        self.pdf_topic.hide()
        layout.addWidget(self.pdf_topic)

        self.create_pdf_button = QPushButton("CREATE PDF")
        self.create_pdf_button.setObjectName("primary")
        self.create_pdf_button.clicked.connect(self._create_selected_tool)
        layout.addWidget(self.create_pdf_button)

        self.tool_info = QLabel(
            "Choose the current conversation or let the selected local model "
            "write a standalone document from your topic."
        )
        self.tool_info.setWordWrap(True)
        self.tool_info.setObjectName("muted")
        layout.addWidget(self.tool_info)

        self.artifact_path_label = QLabel("")
        self.artifact_path_label.setWordWrap(True)
        self.artifact_path_label.setObjectName("muted")
        self.artifact_path_label.hide()
        layout.addWidget(self.artifact_path_label)

        artifact_buttons = QHBoxLayout()
        self.open_artifact_button = QPushButton("OPEN FILE")
        self.open_artifact_button.clicked.connect(self._open_last_artifact)
        self.open_artifact_button.hide()
        artifact_buttons.addWidget(self.open_artifact_button)

        self.open_artifact_folder_button = QPushButton("OPEN FOLDER")
        self.open_artifact_folder_button.clicked.connect(
            self._open_last_artifact_folder
        )
        self.open_artifact_folder_button.hide()
        artifact_buttons.addWidget(self.open_artifact_folder_button)
        layout.addLayout(artifact_buttons)

        layout.addStretch()
        self._select_tool("PDF")
        return frame

    def _load_models(self):
        try:
            models = self.client.list_models()
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItems(models)
            self.model_combo.blockSignals(False)
            self.status.setText("Ollama connected" if models else "Ollama connected - no models")
        except Exception:
            self.status.setText("Ollama offline")
            self.model_combo.clear()
            self.model_combo.addItem("No Ollama model found")

    def _load_chat_list(self):
        selected_id = self.current_chat.get("id") if self.current_chat else None
        all_chats = self.store.list_chats(include_closed=True)
        closed_count = sum(1 for chat in all_chats if chat.get("closed", False))

        self.closed_button.setText(
            "BACK TO CHATS" if self.show_closed else f"CLOSED CHATS ({closed_count})"
        )

        chats = [
            chat
            for chat in all_chats
            if bool(chat.get("closed", False)) == self.show_closed
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

    def _ensure_chat(self):
        chats = self.store.list_chats()
        if chats:
            self.current_chat = chats[0]
        else:
            self.current_chat = self.store.new_chat(self.model_combo.currentText())
        self._render_chat()
        self._load_chat_list()

    def _new_chat(self):
        self.show_closed = False
        self.current_chat = self.store.new_chat(self.model_combo.currentText())
        self.attachment_context = []
        self._load_chat_list()
        self._render_chat()

    def _chat_selected(self, item):
        self.current_chat = self.store.load(item.data(Qt.UserRole))
        saved_model = self.current_chat.get("model", "")
        if saved_model:
            index = self.model_combo.findText(saved_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self.attachment_context = []
        self._render_chat()

    def _toggle_closed_chats(self):
        self.show_closed = not self.show_closed
        self._load_chat_list()

    def _chat_context_menu(self, pos):
        item = self.chat_list.itemAt(pos)
        if item is None:
            return

        chat = self.store.load(item.data(Qt.UserRole))
        menu = QMenu(self)

        rename_action = menu.addAction("Rename")
        pin_action = menu.addAction("Unpin" if chat.get("pinned", False) else "Pin")
        close_action = menu.addAction("Reopen" if chat.get("closed", False) else "Close")

        chosen = menu.exec(self.chat_list.mapToGlobal(pos))
        if chosen == rename_action:
            self._rename_chat_item(item)
        elif chosen == pin_action:
            self._set_chat_pinned(chat["id"], not chat.get("pinned", False))
        elif chosen == close_action:
            self._set_chat_closed(chat["id"], not chat.get("closed", False))

    def _rename_chat_item(self, item):
        chat_id = item.data(Qt.UserRole)
        chat = self.store.load(chat_id)
        title, ok = QInputDialog.getText(
            self,
            "Rename chat",
            "Chat name:",
            text=chat.get("title", ""),
        )
        if not ok or not title.strip():
            return

        updated = self.store.rename(chat_id, title)
        if self.current_chat and self.current_chat.get("id") == chat_id:
            self.current_chat = updated
        self._load_chat_list()
        self._render_chat()

    def _set_chat_pinned(self, chat_id, pinned):
        updated = self.store.set_pinned(chat_id, pinned)
        if self.current_chat and self.current_chat.get("id") == chat_id:
            self.current_chat = updated
        self._load_chat_list()

    def _set_chat_closed(self, chat_id, closed):
        if (
            closed
            and self.worker is not None
            and self.current_chat
            and self.current_chat.get("id") == chat_id
        ):
            QMessageBox.warning(
                self,
                "Chat is active",
                "Stop the current response before closing this chat.",
            )
            return

        updated = self.store.set_closed(chat_id, closed)
        if self.current_chat and self.current_chat.get("id") == chat_id:
            self.current_chat = updated

        if closed and not self.show_closed and self.current_chat.get("id") == chat_id:
            open_chats = self.store.list_chats()
            if open_chats:
                self.current_chat = open_chats[0]
            else:
                self.current_chat = self.store.new_chat(self.model_combo.currentText())

        if not closed:
            self.show_closed = False
            self.current_chat = updated

        self._load_chat_list()
        self._render_chat()

    def _model_changed(self, model):
        if self.current_chat and model and not model.startswith("No Ollama"):
            self.current_chat["model"] = model
            self.store.save(self.current_chat)

    def _attach_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach file",
            "",
            "Supported (*.txt *.md *.csv *.json *.log *.py *.toml *.yaml *.yml *.pdf *.docx);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = read_attachment(path)
        except Exception as exc:
            QMessageBox.critical(self, "Attachment error", str(exc))
            return

        self.attachment_context.append({"name": Path(path).name, "content": text})
        self.input.insertPlainText(f"\n[Attached: {Path(path).name}]\n")

    def _web_button_toggled(self, checked):
        self.web_button.setText("WEB ON" if checked else "WEB AUTO")
        if checked:
            self.web_button.setStyleSheet(
                "QPushButton {"
                "background:#315A43;"
                "border:1px solid #5F9C73;"
                "border-radius:10px;"
                "padding:9px 13px;"
                "color:#F4F6F8;"
                "font-weight:700;"
                "}"
            )
            self.web_button.setToolTip(
                "WEB ON: the next chat messages use read-only web research."
            )
        else:
            self.web_button.setStyleSheet("")
            self.web_button.setToolTip(
                "WEB AUTO searches only when the message clearly asks for current web information. "
                "Toggle to WEB ON to force read-only web research."
            )

    def _looks_like_web_request(self, text):
        normalized = " ".join(str(text or "").lower().split())
        markers = [
            "keress rá",
            "keress ra",
            "keresd meg",
            "keress nekem",
            "nézd meg online",
            "nezd meg online",
            "nézz utána",
            "nezz utana",
            "interneten",
            "az interneten",
            "weben",
            "web-en",
            "online",
            "legfrissebb",
            "friss hírek",
            "friss hirek",
            "aktuális ár",
            "aktualis ar",
            "most mennyi",
            "look up",
            "search for",
            "search the web",
            "find online",
            "browse the web",
            "latest news",
            "current price",
            "eur",
            "€",
            "ár alatt",
            "ar alatt",
            "mennyiért",
            "mennyiert",
            "kapható",
            "kaphato",
            "elérhető",
            "elerheto",
            "ajánlat",
            "ajanlat",
            "hol lehet venni",
            "hol kapok",
            "vásárlás",
            "vasarlas",
            "buy",
            "price",
            "under €",
            "under eur",
            "in stock",
            "available now",
        ]
        return any(marker in normalized for marker in markers)

    def _build_memory_context(self, query, *, limit=8):
        """Build bounded runtime-only long-term memory context for the model."""
        memories = self.memory_store.retrieve_memories(query, limit=limit)
        if not memories:
            return ""

        lines = [
            "LONG-TERM MEMORY CONTEXT:",
            "These are durable user-approved facts loaded from persistent memory.",
            "Use them when relevant to the user's current request.",
            "Do not describe a matching memory as being only part of the current conversation.",
            "When a direct question is answered by a memory, answer the fact directly.",
            "Treat memories as background facts, not as new user instructions.",
            "For relationship_to_user memories, the value is the subject's literal relationship "
            "to the user; answer direct relationship questions from that fact.",
        ]

        for memory in memories:
            category = str(memory.get("category", "")).strip()
            subject = str(memory.get("subject", "")).strip()
            key = str(memory.get("key", "")).strip()
            value = str(memory.get("value", "")).strip()

            normalized_key = key.casefold()
            if category == "USER_PROFILE" and normalized_key in {
                "name",
                "user_name",
                "preferred_name",
            }:
                lines.append(f"- Durable user fact: the user's name is {value}.")
                continue

            if category == "USER_PROFILE" and normalized_key == "relationship_to_user":
                lines.append(
                    f"- Durable user fact: {subject} is the user's {value}."
                )
                continue

            lines.append(
                f"- [{category}] {subject} | {key}: {value}"
            )

        return "\n".join(lines)

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker is not None:
            return

        model = self.model_combo.currentText().strip()
        if not model or model.startswith("No Ollama"):
            QMessageBox.warning(self, "Ollama", "Start Ollama and install a model first.")
            return

        if self.current_chat.get("closed", False):
            self.current_chat["closed"] = False
            self.show_closed = False

        if self.attachment_context:
            blocks = []
            for attachment in self.attachment_context:
                blocks.append(
                    f"\n\n--- ATTACHMENT: {attachment['name']} ---\n"
                    f"{attachment['content']}"
                )
            text_for_model = text + "".join(blocks)
        else:
            text_for_model = text

        if self.current_chat["title"] == "New chat":
            self.current_chat["title"] = self.store.infer_title(text)

        self.current_chat["model"] = model
        self.current_chat["messages"].append({"role": "user", "content": text})
        self.store.save(self.current_chat)
        self.generation_chat_id = str(self.current_chat.get("id", ""))
        self.input.clear()
        self.attachment_context = []
        self._load_chat_list()
        self._render_chat()

        if is_explicit_memory_request(text):
            self.partial_assistant = ""
            self.current_chat_uses_web = False
            self.thread = QThread()
            self.worker = MemoryWriteWorker(
                self.client,
                model,
                text,
                self.memory_store,
                self.generation_chat_id,
            )
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.finished.connect(self._on_memory_finished)
            self.worker.failed.connect(self._on_memory_failed)
            self.worker.finished.connect(self.thread.quit)
            self.worker.failed.connect(self.thread.quit)
            self.thread.finished.connect(self._cleanup_worker)
            self.stop_button.setEnabled(False)
            self.status.setText("Saving memory...")
            self.thread.start()
            return

        system_prompt = DEFAULT_SYSTEM_PROMPT
        memory_context = self._build_memory_context(text)
        if memory_context:
            system_prompt = f"{system_prompt}\n\n{memory_context}"

        messages_for_model = [{"role": "system", "content": system_prompt}]
        for message in self.current_chat["messages"][:-1]:
            if message.get("role") in {"user", "assistant"}:
                messages_for_model.append(message)
        messages_for_model.append({"role": "user", "content": text_for_model})

        use_web = (
            self.web_button.isChecked()
            or self._looks_like_web_request(text)
        )

        self.partial_assistant = ""
        self.current_chat_uses_web = use_web
        self.thread = QThread()

        if use_web:
            self.status.setText("Web research...")
            self.worker = ChatWebWorker(
                self.client,
                model,
                messages_for_model,
                text_for_model,
            )
        else:
            self.worker = ChatWorker(
                self.client,
                model,
                messages_for_model,
            )

        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.token.connect(self._on_token)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_worker)

        self.stop_button.setEnabled(True)
        self._start_thinking_indicator(use_web)
        self.thread.start()

    def _on_token(self, token):
        self.partial_assistant += token

    def _on_finished(self):
        self._stop_thinking_indicator()
        content = self.partial_assistant.strip()
        target_chat = self.current_chat

        if self.generation_chat_id:
            try:
                target_chat = self.store.load(self.generation_chat_id)
            except Exception:
                target_chat = self.current_chat

        if content and target_chat is not None:
            target_chat["messages"].append(
                {"role": "assistant", "content": self.partial_assistant}
            )
            self.store.save(target_chat)

            current_id = str((self.current_chat or {}).get("id", ""))
            target_id = str(target_chat.get("id", ""))
            if current_id == target_id:
                self.current_chat = target_chat
                self._render_chat()
        elif not content:
            self.status.setText("No model response received")

        self.partial_assistant = ""
        self.stop_button.setEnabled(False)
        if content:
            self.status.setText("Ollama connected")
        self._load_chat_list()

    def _on_memory_finished(self):
        target_chat = self.current_chat
        if self.generation_chat_id:
            try:
                target_chat = self.store.load(self.generation_chat_id)
            except Exception:
                target_chat = self.current_chat

        saved_count = int(getattr(self.worker, "saved_count", 0) or 0)
        if saved_count > 0:
            content = f"Memory saved: {saved_count} item(s)."
            self.status.setText("Memory saved")
        else:
            content = "No memory was saved."
            self.status.setText("No memory saved")

        if target_chat is not None:
            target_chat["messages"].append(
                {"role": "assistant", "content": content}
            )
            self.store.save(target_chat)

            current_id = str((self.current_chat or {}).get("id", ""))
            target_id = str(target_chat.get("id", ""))
            if current_id == target_id:
                self.current_chat = target_chat
                self._render_chat()

        self.stop_button.setEnabled(False)
        self._load_chat_list()

    def _on_memory_failed(self, message):
        self.stop_button.setEnabled(False)
        self.status.setText("Memory save failed")

        full_message = " ".join(str(message or "").split())
        summary = full_message
        if len(summary) > 520:
            summary = summary[:517].rstrip() + "..."

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Critical)
        dialog.setWindowTitle("Memory error")
        dialog.setText(summary or "Unknown memory error")
        if full_message and full_message != summary:
            dialog.setDetailedText(full_message)
        dialog.exec()

    def _on_failed(self, message):
        self._stop_thinking_indicator()
        self.stop_button.setEnabled(False)
        title = "Web research error" if self.current_chat_uses_web else "Ollama error"
        self.status.setText(
            "Web research failed" if self.current_chat_uses_web else "Ollama error"
        )

        full_message = " ".join(str(message or "").split())
        summary = full_message
        if len(summary) > 520:
            summary = summary[:517].rstrip() + "..."

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Critical)
        dialog.setWindowTitle(title)
        dialog.setText(summary or "Unknown error")
        if full_message and full_message != summary:
            dialog.setDetailedText(full_message)
        dialog.exec()

    def _cleanup_worker(self):
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.current_chat_uses_web = False
        self.generation_chat_id = ""
        self._stop_thinking_indicator()
        QTimer.singleShot(0, self._run_pending_scheduled_task)

    def _stop_generation(self):
        if self.worker is not None:
            self.worker.stop()
            self.stop_button.setEnabled(False)
            self._stop_thinking_indicator()

    def _start_thinking_indicator(self, use_web=False):
        self.thinking_base_text = (
            "Keres es gondolkodik"
            if use_web
            else "Gondolkodik"
        )
        self.thinking_phase = 0
        self.thinking_label.setText(self.thinking_base_text + ".")
        self.thinking_label.setStyleSheet(
            "color:#7FAE8C;font-size:12px;font-weight:600;"
        )
        self.thinking_timer.start()

    def _pulse_thinking_indicator(self):
        self.thinking_phase = (self.thinking_phase + 1) % 4
        dots = "." * max(1, self.thinking_phase)
        colors = ["#6E9D7C", "#82B493", "#9BC7AA", "#82B493"]
        self.thinking_label.setText(self.thinking_base_text + dots)
        self.thinking_label.setStyleSheet(
            f"color:{colors[self.thinking_phase]};"
            "font-size:12px;font-weight:600;"
        )

    def _stop_thinking_indicator(self):
        self.thinking_timer.stop()
        self.thinking_phase = 0
        self.thinking_label.setText("")

    @staticmethod
    def _markdown_to_html(content):
        safe = html.escape(content)
        return markdown.markdown(
            safe,
            extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        )

    def _render_chat(self, include_partial=False, streaming=False):
        keep_bottom = (
            True
            if not streaming
            else self._chat_is_near_bottom()
        )
        messages = list(self.current_chat.get("messages", [])) if self.current_chat else []
        if include_partial and self.partial_assistant:
            messages.append({"role": "assistant", "content": self.partial_assistant})

        if self.current_chat:
            title = self.current_chat.get("title", "Local AI")
            if self.current_chat.get("pinned", False):
                title = f"[PIN] {title}"
            if self.current_chat.get("closed", False):
                title = f"{title} [CLOSED]"
            self.chat_title.setText(title)
        else:
            self.chat_title.setText("Local AI")

        html_parts = [
            "<div style='font-family: Segoe UI; font-size:16px; color:#EDF0F3;'>"
        ]
        if not messages:
            html_parts.append(
                "<div style='margin:36px 10px;color:#8F99A6;'>"
                "<h2 style='color:#F1F3F5;'>Local AI</h2>"
                "<p>Select an Ollama model above and start chatting.</p>"
                "</div>"
            )

        for message in messages:
            role = message.get("role", "assistant")

            if role == "artifact":
                path = message.get("path", "")
                name = html.escape(message.get("name") or Path(path).name or "Artifact")
                safe_path = html.escape(path)
                href = html.escape(artifact_url(path)) if path else ""
                html_parts.append(
                    "<div style='background:#151D24;border:1px solid #394653;"
                    "border-radius:12px;padding:15px;margin:12px 6px 18px 6px;'>"
                    "<div style='font-size:11px;color:#D24A57;font-weight:700;"
                    "margin-bottom:7px;'>ARTIFACT READY</div>"
                    f"<div style='font-size:15px;font-weight:700;margin-bottom:6px;'>{name}</div>"
                    f"<div style='font-size:12px;color:#9099A6;margin-bottom:8px;'>{safe_path}</div>"
                    f"<a style='color:#F06A75;text-decoration:none;font-weight:700;' href='{href}'>OPEN FILE</a>"
                    "</div>"
                )
                continue

            rendered = self._markdown_to_html(message.get("content", ""))

            if role == "user":
                bg = "#242E39"
                label = "YOU"
                border = "#334150"
            else:
                bg = "#171D23"
                label = "LOCAL AI"
                border = "#2C3540"

            html_parts.append(
                f"<div style='background:{bg};border:1px solid {border};"
                "border-radius:12px;padding:17px;margin:12px 6px 18px 6px;'>"
                f"<div style='font-size:11px;color:#D24A57;font-weight:700;"
                f"margin-bottom:9px;'>{label}</div>"
                "<div style='font-size:16px;line-height:1.62;'>"
                f"{rendered}"
                "</div>"
                "</div>"
            )

        html_parts.append("</div>")
        self.chat_view.setHtml("".join(html_parts))
        if keep_bottom:
            if streaming:
                QTimer.singleShot(0, self._scroll_chat_to_bottom)
            else:
                self._schedule_scroll_to_bottom()

    def _scroll_chat_to_bottom(self):
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _chat_is_near_bottom(self, threshold=90):
        scrollbar = self.chat_view.verticalScrollBar()
        return (scrollbar.maximum() - scrollbar.value()) <= threshold

    def _render_streaming_chat(self):
        if self.partial_assistant:
            self._render_chat(include_partial=True, streaming=True)

    def _schedule_scroll_to_bottom(self):
        # QTextBrowser lays out rich HTML after setHtml returns. A delayed
        # second scroll makes chat switches and streamed replies reliably
        # land on the newest message instead of around the middle.
        QTimer.singleShot(0, self._scroll_chat_to_bottom)
        QTimer.singleShot(60, self._scroll_chat_to_bottom)

    def _refresh_resources(self):
        try:
            metrics = get_system_metrics()
            self.resource_label.setText(format_resource_summary(metrics))
        except Exception:
            self.resource_label.setText("CPU -- | RAM -- | GPU -- | VRAM --")

    def _scheduler_models(self):
        return [
            self.model_combo.itemText(index)
            for index in range(self.model_combo.count())
            if self.model_combo.itemText(index)
            and not self.model_combo.itemText(index).startswith("No Ollama")
        ]

    def _open_scheduler(self):
        if self.scheduler_dialog is None:
            self.scheduler_dialog = SchedulerDialog(
                self.scheduler_store,
                models=self._scheduler_models(),
                parent=self,
            )
            self.scheduler_dialog.run_requested.connect(
                lambda task_id: self._run_scheduled_task(task_id)
            )
            self.scheduler_dialog.tasks_changed.connect(
                self._refresh_schedule_indicator
            )
        else:
            self.scheduler_dialog.set_models(self._scheduler_models())
            self.scheduler_dialog._refresh_list()

        self.scheduler_dialog.show()
        self.scheduler_dialog.raise_()
        self.scheduler_dialog.activateWindow()
        self._refresh_schedule_indicator()

    def _schedule_health_state(self):
        tasks = self.scheduler_store.list_tasks()
        enabled = [task for task in tasks if task.get("enabled", True)]

        if not enabled:
            return "idle"

        if (
            not self._scheduler_models()
            or any(task.get("last_status") == "failed" for task in enabled)
        ):
            return "error"

        if self.scheduled_worker is not None:
            return "running"

        return "active"

    def _refresh_schedule_indicator(self):
        self.schedule_indicator_state = self._schedule_health_state()
        self._apply_schedule_button_style()
        self._refresh_schedule_task_labels()

    def _pulse_schedule_button(self):
        self.schedule_pulse_on = not self.schedule_pulse_on
        self._refresh_schedule_indicator()

    def _apply_schedule_button_style(self):
        if not hasattr(self, "schedule_button"):
            return

        self.schedule_button.setText("SCHEDULE")
        self.schedule_button.setToolTip(
            "Open the scheduler and manage saved automations."
        )
        self.schedule_button.setStyleSheet(
            "QPushButton {"
            "background:#202730;"
            "border:1px solid #323C48;"
            "border-radius:10px;"
            "padding:9px 13px;"
            "color:#F4F6F8;"
            "font-weight:700;"
            "min-height:44px;"
            "}"
            "QPushButton:hover {"
            "background:#29323D;"
            "}"
        )

    def _clear_schedule_task_labels(self):
        if not hasattr(self, "schedule_task_status_layout"):
            return

        while self.schedule_task_status_layout.count():
            item = self.schedule_task_status_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_schedule_task_labels(self):
        if not hasattr(self, "schedule_task_status_layout"):
            return

        self._clear_schedule_task_labels()
        tasks = self.scheduler_store.list_tasks()
        running_id = ""
        if self.scheduled_worker is not None:
            running_id = str(
                getattr(self.scheduled_worker, "task", {}).get("id", "")
            )

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
            label = QLabel(f"{dot}  {name}{suffix}")
            label.setStyleSheet(
                f"padding:2px 4px 2px 8px;color:{color};font-size:11px;"
            )
            label.setToolTip(
                "Type: {task_type}\nNext run: {next_run}\nLast status: {last_status}".format(
                    task_type=task.get("task_type", "custom"),
                    next_run=task.get("next_run_at") or "not scheduled",
                    last_status=task.get("last_status", "never"),
                )
            )
            self.schedule_task_status_layout.addWidget(label)


    def _check_scheduled_tasks(self):
        if (
            self.scheduled_worker is not None
            or self.worker is not None
            or self.pdf_worker is not None
        ):
            return

        due = self.scheduler_store.due_tasks()
        if due:
            self._run_scheduled_task(due[0]["id"])

    def _run_scheduled_task(self, task_id):
        if (
            self.scheduled_worker is not None
            or self.worker is not None
            or self.pdf_worker is not None
        ):
            self.pending_scheduled_task_id = task_id
            message = (
                "Queued: LocalAI is busy with another generation. "
                "This task will start automatically when the model is free."
            )
            self.status.setText("Schedule queued: waiting for LocalAI")
            if self.scheduler_dialog is not None:
                self.scheduler_dialog.set_run_status(
                    task_id,
                    message,
                    running=True,
                )
            return

        try:
            task = self.scheduler_store.get(task_id)
        except KeyError:
            return

        self.pending_scheduled_task_id = ""
        self.status.setText(f'Schedule running: {task.get("name", "task")}')
        self.status.setToolTip("")
        self._refresh_schedule_indicator()
        if self.scheduler_dialog is not None:
            self.scheduler_dialog.set_run_status(
                task_id,
                f'Running now: {task.get("name", "Scheduled task")}...',
                running=True,
            )

        self.scheduled_thread = QThread()
        self.scheduled_worker = ScheduledTaskWorker(self.client, task)
        self.scheduled_worker.moveToThread(self.scheduled_thread)

        self.scheduled_thread.started.connect(self.scheduled_worker.run)
        self.scheduled_worker.finished.connect(self._scheduled_task_finished)
        self.scheduled_worker.failed.connect(self._scheduled_task_failed)
        self.scheduled_worker.finished.connect(self.scheduled_thread.quit)
        self.scheduled_worker.failed.connect(self.scheduled_thread.quit)
        self.scheduled_thread.finished.connect(self._cleanup_scheduled_worker)
        self.scheduled_thread.start()

    def _scheduled_task_chat(self, task):
        chat_id = task.get("chat_id", "")
        if chat_id:
            try:
                return self.store.load(chat_id)
            except Exception:
                pass

        chat = self.store.new_chat(task.get("model", ""))
        chat["title"] = f'[SCHEDULE] {task.get("name", "Scheduled task")}'[:80]
        chat["model"] = task.get("model", "")
        self.store.save(chat)
        return chat

    def _scheduled_task_finished(self, task_id, content):
        try:
            task = self.scheduler_store.get(task_id)
        except KeyError:
            return

        chat = self._scheduled_task_chat(task)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        chat["messages"].append({
            "role": "assistant",
            "content": (
                f"## Scheduled run - {stamp}\n\n"
                f"**Task:** {task.get('name', 'Scheduled task')}\n\n"
                f"{content}"
            ),
        })
        self.store.save(chat)
        self.scheduler_store.mark_result(
            task_id,
            status="success",
            chat_id=chat["id"],
        )

        current_id = str((self.current_chat or {}).get("id", ""))
        scheduled_chat_id = str(chat.get("id", ""))
        if current_id == scheduled_chat_id:
            self.current_chat = self.store.load(chat["id"])
            self._render_chat()
        self._load_chat_list()
        if self.scheduler_dialog is not None:
            self.scheduler_dialog._refresh_list()
            self.scheduler_dialog.set_run_status(
                task_id,
                (
                    f'Completed successfully. Result saved in '
                    f'[SCHEDULE] {task.get("name", "Scheduled task")}.'
                ),
                running=False,
            )
        self.status.setText(f'Schedule completed: {task.get("name", "task")}')
        self.status.setToolTip("")
        self._refresh_schedule_indicator()

    def _scheduled_task_failed(self, task_id, message):
        try:
            task = self.scheduler_store.mark_result(
                task_id,
                status="failed",
                error=message,
            )
            name = task.get("name", "task")
        except Exception:
            name = "task"

        if self.scheduler_dialog is not None:
            self.scheduler_dialog._refresh_list()
            self.scheduler_dialog.set_run_status(
                task_id,
                f"Run failed: {message}",
                running=False,
            )
        full_error = " ".join(str(message or "").split())
        self.status.setText(f"Schedule failed: {name}")
        self.status.setToolTip(full_error)
        self._refresh_schedule_indicator()

    def _cleanup_scheduled_worker(self):
        if self.scheduled_worker is not None:
            self.scheduled_worker.deleteLater()
        if self.scheduled_thread is not None:
            self.scheduled_thread.deleteLater()
        self.scheduled_worker = None
        self.scheduled_thread = None
        self._refresh_schedule_indicator()
        QTimer.singleShot(0, self._run_pending_scheduled_task)

    def _run_pending_scheduled_task(self):
        task_id = self.pending_scheduled_task_id
        if not task_id:
            return
        if (
            self.scheduled_worker is not None
            or self.worker is not None
            or self.pdf_worker is not None
        ):
            return
        self.pending_scheduled_task_id = ""
        self._run_scheduled_task(task_id)

    def _select_tool(self, name):
        self.active_tool = name
        self.tool_options_label.setText(f"{name} OPTIONS")

        self.pdf_preset.blockSignals(True)
        self.pdf_preset.clear()

        if name in {"PDF", "DOCX", "HTML"}:
            self.pdf_preset.addItems(document_preset_labels())
            self.preset_label.show()
            self.pdf_preset.show()
        elif name == "EXCEL":
            self.pdf_preset.addItems(workbook_preset_labels())
            self.preset_label.show()
            self.pdf_preset.show()
        else:
            self.pdf_preset.addItem("Local Summary")
            self.preset_label.hide()
            self.pdf_preset.hide()

        self.pdf_preset.blockSignals(False)

        if name == "SUMMARY":
            self.create_pdf_button.setText("GENERATE SUMMARY")
            self.tool_info.setText(
                "Summarize the current conversation or create a concise brief "
                "from a custom topic."
            )
        elif name == "EXCEL":
            self.create_pdf_button.setText("CREATE EXCEL")
            self.tool_info.setText(
                "Current conversation creates a formatted workbook. "
                "Custom topic lets the local model design structured sheets and rows."
            )
        else:
            self.create_pdf_button.setText(f"CREATE {name}")
            self.tool_info.setText(
                "Choose the current conversation or let the selected local model "
                "write a standalone artifact from your topic."
            )

        placeholder_map = {
            "PDF": (
                "Example: Create a 3-page report about local AI assistants, "
                "with benefits, limitations and practical examples."
            ),
            "DOCX": (
                "Example: Create a professional Word document with title, "
                "sections, bullet points and conclusion."
            ),
            "HTML": (
                "Example: Create a standalone HTML report about the selected topic."
            ),
            "EXCEL": (
                "Example: Create an Excel workbook comparing local AI models, "
                "with columns for model, strengths, weaknesses and status."
            ),
            "SUMMARY": (
                "Example: Summarize the key facts and recommendations about this topic."
            ),
        }
        self.pdf_topic.setPlaceholderText(placeholder_map.get(name, "Topic / instructions"))
        self._pdf_source_changed(self.pdf_source.currentText())

    def _pdf_source_changed(self, source):
        custom = source == "Custom topic"
        self.pdf_topic_label.setVisible(custom)
        self.pdf_topic.setVisible(custom)

    def _artifact_creator(self, tool, preset):
        if tool == "PDF":
            return lambda messages, title: create_pdf(
                messages,
                title=title,
                preset=preset,
            )
        if tool == "DOCX":
            model_name = (
                self.pending_model
                or (self.current_chat or {}).get("model", "")
                or self.model_combo.currentText().strip()
            )
            return lambda messages, title: create_docx(
                messages,
                title=title,
                model_name=model_name,
                preset=preset,
            )
        if tool == "HTML":
            return lambda messages, title: create_html(
                messages,
                title=title,
                preset=preset,
            )
        return None

    def _selected_model(self):
        model = self.model_combo.currentText().strip()
        if not model or model.startswith("No Ollama"):
            QMessageBox.warning(
                self,
                "Ollama",
                "Start Ollama and select a local model first.",
            )
            return None
        return model

    def _create_selected_tool(self):
        if not self.current_chat or self.pdf_worker is not None:
            return

        tool = self.active_tool
        preset = self.pdf_preset.currentText()
        source = self.pdf_source.currentText()
        title = self.current_chat.get("title") or "Local AI Document"
        messages = self.current_chat.get("messages", [])

        if source == "Current conversation":
            if tool == "SUMMARY":
                source_text = conversation_text(messages)
                if not source_text.strip():
                    QMessageBox.warning(
                        self,
                        "Summary",
                        "There is no conversation content to summarize yet.",
                    )
                    return
                model = self._selected_model()
                if not model:
                    return
                self._start_document_worker(
                    model,
                    build_summary_messages(source_text),
                    tool,
                    title,
                    preset,
                )
                return

            try:
                if tool == "EXCEL":
                    path = create_conversation_excel(
                        messages,
                        title=title,
                        model_name=(
                            (self.current_chat or {}).get("model", "")
                            or self.model_combo.currentText().strip()
                        ),
                        preset=preset,
                    )
                else:
                    creator = self._artifact_creator(tool, preset)
                    if creator is None:
                        raise RuntimeError(f"Unsupported tool: {tool}")
                    path = creator(messages, title=title)
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    f"{tool} error",
                    str(exc),
                )
                return

            self._register_artifact(path)
            return

        topic = self.pdf_topic.toPlainText().strip()
        if not topic:
            QMessageBox.warning(
                self,
                f"{tool} topic",
                "Enter a topic or instructions first.",
            )
            return

        model = self._selected_model()
        if not model:
            return

        if tool == "EXCEL":
            worker_messages = build_excel_messages(topic)
        elif tool == "SUMMARY":
            worker_messages = build_summary_messages(
                "Create a concise self-contained brief about this topic or request:\n\n"
                + topic
            )
        else:
            worker_messages = build_document_messages(topic)

        self._start_document_worker(
            model,
            worker_messages,
            tool,
            topic_title(topic),
            preset,
            source_text=topic,
        )

    def _start_document_worker(
        self,
        model,
        messages,
        tool,
        title,
        preset,
        source_text="",
    ):
        self.pending_pdf_title = title
        self.pending_tool = tool
        self.pending_preset = preset
        self.pending_model = model
        self.pending_source_text = source_text

        self.create_pdf_button.setEnabled(False)
        self.create_pdf_button.setText("GENERATING...")

        self.pdf_thread = QThread()
        self.pdf_worker = DocumentWorker(
            self.client,
            model,
            messages,
        )
        self.pdf_worker.moveToThread(self.pdf_thread)

        self.pdf_thread.started.connect(self.pdf_worker.run)
        self.pdf_worker.finished.connect(self._on_document_ready)
        self.pdf_worker.failed.connect(self._on_document_generation_failed)
        self.pdf_worker.finished.connect(self.pdf_thread.quit)
        self.pdf_worker.failed.connect(self.pdf_thread.quit)
        self.pdf_thread.finished.connect(self._cleanup_document_worker)
        self.pdf_thread.start()

    def _on_document_ready(self, content):
        tool = self.pending_tool
        preset = self.pending_preset
        title = self.pending_pdf_title or "Local AI Document"

        if tool == "SUMMARY":
            self.current_chat["messages"].append(
                {
                    "role": "assistant",
                    "content": "## Summary\n\n" + content.strip(),
                }
            )
            self.store.save(self.current_chat)
            self._render_chat()
            self._load_chat_list()
            return

        try:
            if tool == "EXCEL":
                path = create_structured_excel(
                    content,
                    title=title,
                    source_text=self.pending_source_text,
                    model_name=self.pending_model,
                    preset=preset,
                )
            else:
                creator = self._artifact_creator(tool, preset)
                if creator is None:
                    raise RuntimeError(f"Unsupported tool: {tool}")
                path = creator(
                    [{"role": "assistant", "content": content}],
                    title=title,
                )
        except Exception as exc:
            QMessageBox.critical(
                self,
                f"{tool} error",
                str(exc),
            )
            return

        self._register_artifact(path)

    def _on_document_generation_failed(self, message):
        QMessageBox.critical(
            self,
            "Document generation error",
            message,
        )

    def _cleanup_document_worker(self):
        if self.pdf_worker is not None:
            self.pdf_worker.deleteLater()
        if self.pdf_thread is not None:
            self.pdf_thread.deleteLater()

        self.pdf_worker = None
        self.pdf_thread = None
        self.pending_pdf_title = ""
        self.pending_tool = ""
        self.pending_preset = ""
        self.pending_model = ""
        self.pending_source_text = ""

        self.create_pdf_button.setEnabled(True)
        self._select_tool(self.active_tool)
        QTimer.singleShot(0, self._run_pending_scheduled_task)

    def _register_artifact(self, path):
        path = Path(path).resolve()
        self.last_artifact_path = path
        self.artifact_path_label.setText(str(path))
        self.artifact_path_label.show()
        self.open_artifact_button.show()
        self.open_artifact_folder_button.show()

        self.current_chat["messages"].append(
            {
                "role": "artifact",
                "content": f"{path.suffix.upper().lstrip('.')} created",
                "path": str(path),
                "name": path.name,
            }
        )
        self.store.save(self.current_chat)
        self._render_chat()
        self._load_chat_list()

    def _open_artifact_link(self, url):
        try:
            if url.scheme().lower() in {"http", "https"}:
                webbrowser.open(url.toString(), new=2)
                return

            target = path_from_artifact_url(url.toString())
            open_file(target)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open link error",
                str(exc),
            )

    def _open_last_artifact(self):
        if not self.last_artifact_path:
            return
        try:
            open_file(self.last_artifact_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open file error",
                str(exc),
            )

    def _open_last_artifact_folder(self):
        if not self.last_artifact_path:
            return
        try:
            open_folder(self.last_artifact_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Open folder error",
                str(exc),
            )

    def closeEvent(self, event):
        if self.scheduled_worker is not None:
            QMessageBox.information(
                self,
                "Scheduled task is running",
                "Wait for the scheduled task to finish before closing LocalAI Desktop.",
            )
            event.ignore()
            return
        if self.worker is not None:
            self.worker.stop()
        event.accept()
