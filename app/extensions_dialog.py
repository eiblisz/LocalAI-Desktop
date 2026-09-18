from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .extension_store import (
    AUTH_TYPES,
    EXTENSION_TYPES,
    ExtensionStore,
    test_extension_connection,
)


class ExtensionTestWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, extension):
        super().__init__()
        self.extension = dict(extension or {})

    @Slot()
    def run(self):
        try:
            self.finished.emit(test_extension_connection(self.extension))
        except Exception as exc:
            self.failed.emit(str(exc))


class ExtensionsDialog(QDialog):
    def __init__(self, store: ExtensionStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.current_id = ""
        self.test_thread = None
        self.test_worker = None

        self.setWindowTitle("Extensions")
        self.resize(980, 700)
        self._build_ui()
        self._refresh_list()
        self._new_extension()

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        title = QLabel("EXTENSIONS")
        title.setStyleSheet("font-size:17px;font-weight:700;")
        left.addWidget(title)

        intro = QLabel(
            "Saved extension endpoints live in your private LocalAI runtime data. "
            "Enabling an extension does not give the chat access yet."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9099A6;")
        left.addWidget(intro)

        self.extension_list = QListWidget()
        self.extension_list.itemClicked.connect(self._extension_selected)
        left.addWidget(self.extension_list, 1)

        new_button = QPushButton("NEW EXTENSION")
        new_button.clicked.connect(self._new_extension)
        left.addWidget(new_button)
        root.addLayout(left, 1)

        right = QVBoxLayout()

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Example: ComfyUI")
        form.addRow("Name", self.name_edit)

        self.type_combo = QComboBox()
        for key, label in EXTENSION_TYPES.items():
            self.type_combo.addItem(label, key)
        form.addRow("Type", self.type_combo)

        self.endpoint_edit = QLineEdit()
        self.endpoint_edit.setPlaceholderText("Example: http://127.0.0.1:8188")
        form.addRow("Endpoint", self.endpoint_edit)

        self.capabilities_edit = QLineEdit()
        self.capabilities_edit.setPlaceholderText(
            "Example: image_generate, image_edit"
        )
        form.addRow("Capabilities", self.capabilities_edit)

        self.auth_combo = QComboBox()
        for key, label in AUTH_TYPES.items():
            self.auth_combo.addItem(label, key)
        form.addRow("Authentication", self.auth_combo)

        auth_note = QLabel(
            "Credentials are intentionally not stored here. Secret storage and "
            "credential binding will be added as a separate protected layer."
        )
        auth_note.setWordWrap(True)
        auth_note.setStyleSheet("color:#7F8995;font-size:12px;")
        form.addRow("", auth_note)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setValue(10)
        self.timeout_spin.setSuffix(" s")
        form.addRow("Timeout", self.timeout_spin)

        self.enabled_button = QPushButton("DISABLED")
        self.enabled_button.setCheckable(True)
        self.enabled_button.toggled.connect(self._enabled_changed)
        form.addRow("State", self.enabled_button)

        right.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#9099A6;")
        right.addWidget(self.status_label)

        buttons = QHBoxLayout()

        self.save_button = QPushButton("SAVE")
        self.save_button.clicked.connect(self._save_extension)
        buttons.addWidget(self.save_button)

        self.test_button = QPushButton("TEST CONNECTION")
        self.test_button.clicked.connect(self._test_connection)
        buttons.addWidget(self.test_button)

        self.delete_button = QPushButton("DELETE")
        self.delete_button.clicked.connect(self._delete_extension)
        buttons.addWidget(self.delete_button)

        right.addLayout(buttons)

        note = QLabel(
            "Foundation slice: registry, enable/disable state, capabilities and "
            "connection testing only. Runtime tool injection is deliberately not enabled yet."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7F8995;font-size:12px;")
        right.addWidget(note)
        right.addStretch()

        root.addLayout(right, 2)

    def _enabled_changed(self, checked):
        self.enabled_button.setText("ENABLED" if checked else "DISABLED")

    def _refresh_list(self, selected_id=None):
        selected_id = selected_id or self.current_id
        self.extension_list.clear()
        selected_row = -1

        for row, extension in enumerate(self.store.list_extensions()):
            enabled = bool(extension.get("enabled", False))
            status = str(extension.get("last_status", "never"))
            if not enabled:
                dot = "○"
            elif status in {"connected", "auth_required"}:
                dot = "●"
            elif status == "error":
                dot = "!"
            else:
                dot = "•"

            label = EXTENSION_TYPES.get(
                extension.get("type", ""),
                extension.get("type", "extension"),
            )
            item = QListWidgetItem(
                f"{dot}  {extension.get('name', 'Extension')}  —  {label}"
            )
            item.setData(Qt.UserRole, extension.get("id", ""))
            item.setToolTip(
                "Endpoint: {endpoint}\nCapabilities: {capabilities}\n"
                "Last status: {status}\nLast tested: {tested}".format(
                    endpoint=extension.get("endpoint") or "not set",
                    capabilities=", ".join(extension.get("capabilities") or [])
                    or "none",
                    status=status,
                    tested=extension.get("last_tested") or "never",
                )
            )
            self.extension_list.addItem(item)
            if extension.get("id") == selected_id:
                selected_row = row

        if selected_row >= 0:
            self.extension_list.setCurrentRow(selected_row)

    def _new_extension(self):
        self.current_id = ""
        self.name_edit.clear()
        self.type_combo.setCurrentIndex(0)
        self.endpoint_edit.clear()
        self.capabilities_edit.clear()
        self.auth_combo.setCurrentIndex(0)
        self.timeout_spin.setValue(10)
        self.enabled_button.setChecked(False)
        self.status_label.setText(
            "Create an extension entry. The chat cannot use it until a later runtime wiring step."
        )
        self.delete_button.setEnabled(False)

    def _extension_selected(self, item):
        extension_id = str(item.data(Qt.UserRole) or "")
        try:
            extension = self.store.get(extension_id)
        except Exception as exc:
            QMessageBox.critical(self, "Extensions", str(exc))
            return

        self.current_id = extension_id
        self.name_edit.setText(extension.get("name", ""))

        index = self.type_combo.findData(extension.get("type", "http_api"))
        self.type_combo.setCurrentIndex(max(index, 0))

        self.endpoint_edit.setText(extension.get("endpoint", ""))
        self.capabilities_edit.setText(
            ", ".join(extension.get("capabilities") or [])
        )

        auth_index = self.auth_combo.findData(extension.get("auth_type", "none"))
        self.auth_combo.setCurrentIndex(max(auth_index, 0))

        self.timeout_spin.setValue(
            max(1, min(int(float(extension.get("timeout", 10) or 10)), 120))
        )
        self.enabled_button.setChecked(bool(extension.get("enabled", False)))

        status = extension.get("last_status", "never")
        message = extension.get("last_message", "")
        tested = extension.get("last_tested") or "never"
        self.status_label.setText(
            f"Last connection test: {status} ({tested})"
            + (f" — {message}" if message else "")
        )
        self.delete_button.setEnabled(True)

    def _form_payload(self):
        return {
            "id": self.current_id,
            "name": self.name_edit.text(),
            "type": self.type_combo.currentData(),
            "endpoint": self.endpoint_edit.text(),
            "enabled": self.enabled_button.isChecked(),
            "auth_type": self.auth_combo.currentData(),
            "capabilities": self.capabilities_edit.text(),
            "timeout": self.timeout_spin.value(),
        }

    def _save_extension(self, _checked=False, *, silent=False):
        try:
            extension = self.store.save(self._form_payload())
        except Exception as exc:
            if silent:
                self.status_label.setText(f"Save failed: {exc}")
            else:
                QMessageBox.critical(self, "Extension save error", str(exc))
            return None

        self.current_id = extension["id"]
        self.delete_button.setEnabled(True)
        self._refresh_list(selected_id=self.current_id)
        if not silent:
            self.status_label.setText("Extension saved.")
        return extension

    def _delete_extension(self):
        if not self.current_id:
            return

        answer = QMessageBox.question(
            self,
            "Delete extension",
            "Delete this extension entry? No external service will be modified.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.store.delete(self.current_id)
        except Exception as exc:
            QMessageBox.critical(self, "Extension delete error", str(exc))
            return

        self._refresh_list()
        self._new_extension()

    def _test_connection(self):
        if self.test_worker is not None:
            return

        extension = self._save_extension(silent=True)
        if extension is None:
            return

        self.test_button.setEnabled(False)
        self.status_label.setText("Testing connection...")

        self.test_thread = QThread(self)
        self.test_worker = ExtensionTestWorker(extension)
        self.test_worker.moveToThread(self.test_thread)

        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self._test_finished)
        self.test_worker.failed.connect(self._test_failed)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_worker.failed.connect(self.test_thread.quit)
        self.test_thread.finished.connect(self._cleanup_test_worker)
        self.test_thread.start()

    def _test_finished(self, result):
        status = str(result.get("status", "error"))
        message = str(result.get("message", ""))
        try:
            updated = self.store.record_test_result(
                self.current_id,
                status,
                message,
            )
        except Exception as exc:
            self.status_label.setText(f"Connection test finished but status save failed: {exc}")
            return

        self.status_label.setText(
            f"Connection test: {updated.get('last_status')} — "
            f"{updated.get('last_message', '')}"
        )
        self._refresh_list(selected_id=self.current_id)

    def _test_failed(self, message):
        if self.current_id:
            try:
                self.store.record_test_result(
                    self.current_id,
                    "error",
                    message,
                )
            except Exception:
                pass
        self.status_label.setText(f"Connection test failed: {message}")
        self._refresh_list(selected_id=self.current_id)

    def _cleanup_test_worker(self):
        if self.test_worker is not None:
            self.test_worker.deleteLater()
        if self.test_thread is not None:
            self.test_thread.deleteLater()
        self.test_worker = None
        self.test_thread = None
        self.test_button.setEnabled(True)

    def closeEvent(self, event):
        if self.test_worker is not None:
            QMessageBox.information(
                self,
                "Extension test is running",
                "Wait for the connection test to finish before closing Extensions.",
            )
            event.ignore()
            return
        event.accept()
