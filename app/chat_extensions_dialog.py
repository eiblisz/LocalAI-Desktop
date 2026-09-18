from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class ChatExtensionsDialog(QDialog):
    saved = Signal(list)

    def __init__(self, extension_store, chat_store, chat_id, parent=None):
        super().__init__(parent)
        self.extension_store = extension_store
        self.chat_store = chat_store
        self.chat_id = str(chat_id or "")

        self.setWindowTitle("Chat Extensions")
        self.resize(700, 540)
        self._build_ui()
        self._load_extensions()

    def _build_ui(self):
        root = QVBoxLayout(self)

        title = QLabel("ATTACH EXTENSIONS TO THIS CHAT")
        title.setStyleSheet("font-size:17px;font-weight:700;")
        root.addWidget(title)

        intro = QLabel(
            "Choose which installed extensions belong to this conversation. "
            "Attachments are saved per chat. This slice does not execute extensions "
            "or inject credentials into the model."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9099A6;")
        root.addWidget(intro)

        self.extension_list = QListWidget()
        root.addWidget(self.extension_list, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#9099A6;font-size:12px;")
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()

        save_button = QPushButton("SAVE ATTACHMENTS")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)

        cancel_button = QPushButton("CANCEL")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        root.addLayout(buttons)

    def _load_extensions(self):
        chat = self.chat_store.load(self.chat_id)
        attached = set(chat.get("attached_extensions") or [])
        installed = self.extension_store.list_extensions()
        installed_ids = {str(item.get("id", "")) for item in installed}

        self.extension_list.clear()

        for extension in installed:
            extension_id = str(extension.get("id", ""))
            enabled = bool(extension.get("enabled", False))
            state = "ENABLED" if enabled else "DISABLED"
            extension_type = str(extension.get("type", "extension")).replace("_", " ").upper()

            item = QListWidgetItem(
                f"{extension.get('name', 'Extension')}  —  {extension_type}  [{state}]"
            )
            item.setData(Qt.UserRole, extension_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if extension_id in attached
                else Qt.CheckState.Unchecked
            )
            item.setToolTip(
                "Capabilities: {capabilities}\n"
                "Connection status: {status}\n"
                "Chat runtime execution: not enabled yet".format(
                    capabilities=", ".join(extension.get("capabilities") or []) or "none",
                    status=extension.get("last_status", "never"),
                )
            )
            self.extension_list.addItem(item)

        stale_count = len(attached - installed_ids)
        if not installed:
            self.status_label.setText(
                "No installed extensions. Add extensions from the Extensions catalog first."
            )
        elif stale_count:
            self.status_label.setText(
                f"{stale_count} previously attached extension(s) no longer exist and "
                "will be removed when you save."
            )
        else:
            self.status_label.setText(
                "Checked entries will be attached to this chat only."
            )

    def _selected_ids(self):
        selected = []
        for row in range(self.extension_list.count()):
            item = self.extension_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                extension_id = str(item.data(Qt.UserRole) or "")
                if extension_id and extension_id not in selected:
                    selected.append(extension_id)
        return selected

    def _save(self):
        chat = self.chat_store.load(self.chat_id)
        selected = self._selected_ids()
        chat["attached_extensions"] = selected
        self.chat_store.save(chat)
        self.saved.emit(selected)
        self.accept()
