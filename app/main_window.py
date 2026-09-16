from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import APP_NAME, DEFAULT_SYSTEM_PROMPT
from .file_reader import read_attachment
from .ollama_client import OllamaClient
from .pdf_tool import create_red_professional_pdf
from .storage import ChatStore
from .workers import ChatWorker


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
QLabel#muted {
    color: #9099A6;
    font-size: 12px;
}
QPushButton {
    background: #202730;
    border: 1px solid #323C48;
    border-radius: 10px;
    padding: 10px 14px;
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
    min-height: 60px;
    font-weight: 700;
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
    border-radius: 9px;
    padding: 10px;
    margin: 2px 0;
}
QListWidget::item:selected {
    background: #252E38;
}
QTextBrowser {
    background: #0F1318;
    border: none;
    padding: 20px;
}
QTextEdit {
    background: #161C23;
    border: 1px solid #35404C;
    border-radius: 12px;
    padding: 10px;
}
QSplitter::handle {
    background: #252D36;
    width: 1px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalAI Desktop")
        self.resize(1420, 900)

        self.client = OllamaClient()
        self.store = ChatStore()
        self.current_chat = None
        self.attachment_context = []
        self.thread = None
        self.worker = None
        self.partial_assistant = ""

        self.setStyleSheet(STYLE)
        self._build_ui()
        self._load_models()
        self._load_chat_list()
        self._ensure_chat()

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
        top_layout.addStretch()

        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._model_changed)
        top_layout.addWidget(self.model_combo)

        self.status = QLabel("Ollama: checking...")
        self.status.setObjectName("muted")
        top_layout.addWidget(self.status)

        root.addWidget(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_chat_panel())
        splitter.addWidget(self._build_tools_panel())
        splitter.setSizes([260, 850, 310])
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

        label = QLabel("Conversations")
        label.setObjectName("muted")
        layout.addWidget(label)

        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self._chat_selected)
        layout.addWidget(self.chat_list, 1)

        note = QLabel("Stored locally on this PC")
        note.setObjectName("muted")
        layout.addWidget(note)
        return frame

    def _build_chat_panel(self):
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        layout.addWidget(self.chat_view, 1)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(12, 10, 12, 12)

        attach = QPushButton("Attach")
        attach.clicked.connect(self._attach_file)
        input_row.addWidget(attach)

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

        for text in ["PDF", "DOCX", "EXCEL", "SUMMARY"]:
            button = QPushButton(text)
            button.setObjectName("toolButton")
            if text == "PDF":
                button.clicked.connect(self._pdf_selected)
            else:
                button.clicked.connect(
                    lambda _checked=False, name=text: self._tool_placeholder(name)
                )
            layout.addWidget(button)

        layout.addSpacing(12)
        options = QLabel("PDF OPTIONS")
        options.setObjectName("muted")
        layout.addWidget(options)

        preset_label = QLabel("PDF preset")
        preset_label.setObjectName("muted")
        layout.addWidget(preset_label)

        self.pdf_preset = QComboBox()
        self.pdf_preset.addItem("Red Professional")
        layout.addWidget(self.pdf_preset)

        source_label = QLabel("Source")
        source_label.setObjectName("muted")
        layout.addWidget(source_label)

        self.pdf_source = QComboBox()
        self.pdf_source.addItem("Current conversation")
        layout.addWidget(self.pdf_source)

        create_pdf = QPushButton("CREATE PDF")
        create_pdf.setObjectName("primary")
        create_pdf.clicked.connect(self._create_pdf)
        layout.addWidget(create_pdf)

        info = QLabel("The PDF is generated directly from the current conversation.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)

        layout.addStretch()
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
        self.chat_list.clear()
        for chat in self.store.list_chats():
            item = QListWidgetItem(chat.get("title", "New chat"))
            item.setData(Qt.UserRole, chat["id"])
            self.chat_list.addItem(item)

    def _ensure_chat(self):
        chats = self.store.list_chats()
        if chats:
            self.current_chat = chats[0]
        else:
            self.current_chat = self.store.new_chat(self.model_combo.currentText())
        self._render_chat()

    def _new_chat(self):
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

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker is not None:
            return

        model = self.model_combo.currentText().strip()
        if not model or model.startswith("No Ollama"):
            QMessageBox.warning(self, "Ollama", "Start Ollama and install a model first.")
            return

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
        self.input.clear()
        self.attachment_context = []
        self._load_chat_list()
        self._render_chat()

        messages_for_model = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        for message in self.current_chat["messages"][:-1]:
            messages_for_model.append(message)
        messages_for_model.append({"role": "user", "content": text_for_model})

        self.partial_assistant = ""
        self.thread = QThread()
        self.worker = ChatWorker(self.client, model, messages_for_model)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.token.connect(self._on_token)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_worker)

        self.stop_button.setEnabled(True)
        self.thread.start()

    def _on_token(self, token):
        self.partial_assistant += token
        self._render_chat(include_partial=True)

    def _on_finished(self):
        if self.partial_assistant.strip():
            self.current_chat["messages"].append(
                {"role": "assistant", "content": self.partial_assistant}
            )
            self.store.save(self.current_chat)
        self.partial_assistant = ""
        self.stop_button.setEnabled(False)
        self._render_chat()
        self._load_chat_list()

    def _on_failed(self, message):
        self.stop_button.setEnabled(False)
        QMessageBox.critical(self, "Ollama error", message)

    def _cleanup_worker(self):
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def _stop_generation(self):
        if self.worker is not None:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _render_chat(self, include_partial=False):
        messages = list(self.current_chat.get("messages", [])) if self.current_chat else []
        if include_partial and self.partial_assistant:
            messages.append({"role": "assistant", "content": self.partial_assistant})

        html_parts = ["<div style='font-family: Segoe UI; max-width: 900px;'>"]
        if not messages:
            html_parts.append(
                "<div style='margin:40px 10px;color:#8F99A6;'>"
                "<h2 style='color:#F1F3F5;'>Local AI</h2>"
                "<p>Select an Ollama model above and start chatting.</p>"
                "</div>"
            )

        for message in messages:
            role = message.get("role", "assistant")
            content = (
                message.get("content", "")
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )

            if role == "user":
                bg = "#25303C"
                label = "YOU"
            else:
                bg = "#1A2027"
                label = "LOCAL AI"

            html_parts.append(
                f"<div style='background:{bg};border:1px solid #303A45;"
                "border-radius:12px;padding:16px;margin:12px 4px;'>"
                f"<div style='font-size:11px;color:#C94A57;font-weight:700;"
                f"margin-bottom:8px;'>{label}</div>"
                f"<div style='color:#EDF0F3;line-height:1.45;'>{content}</div>"
                "</div>"
            )

        html_parts.append("</div>")
        self.chat_view.setHtml("".join(html_parts))
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _pdf_selected(self):
        self.pdf_preset.setFocus()

    def _create_pdf(self):
        if not self.current_chat:
            return
        try:
            path = create_red_professional_pdf(
                self.current_chat.get("messages", []),
                title=self.current_chat.get("title") or "Local AI Report",
            )
        except Exception as exc:
            QMessageBox.critical(self, "PDF error", str(exc))
            return

        QMessageBox.information(self, "PDF created", f"PDF saved to:\n{path}")

    def _tool_placeholder(self, name):
        QMessageBox.information(
            self,
            name,
            f"{name} is reserved in the MVP. PDF is the first fully implemented document tool.",
        )

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.stop()
        event.accept()
