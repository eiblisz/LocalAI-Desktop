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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .discord_bot_bridge import (
    test_discord_bot_token,
    validate_bot_token,
)
from .discord_webhook import (
    send_discord_test_message,
    test_discord_webhook,
    validate_discord_webhook_url,
)
from .extension_catalog import (
    PRESET_CATEGORIES,
    find_preset,
    preset_to_registry_entry,
    search_presets,
)
from .extension_store import (
    AUTH_TYPES,
    EXTENSION_TYPES,
    ExtensionStore,
    test_extension_connection,
)
from .secret_store import SecretStore
from .ui_theme import muted_label_style


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


class DiscordWebhookWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, webhook_url, mode="test", timeout=10):
        super().__init__()
        self.webhook_url = webhook_url
        self.mode = mode
        self.timeout = timeout

    @Slot()
    def run(self):
        try:
            if self.mode == "send":
                result = send_discord_test_message(
                    self.webhook_url,
                    timeout=self.timeout,
                )
            else:
                result = test_discord_webhook(
                    self.webhook_url,
                    timeout=self.timeout,
                )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class DiscordBotTestWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, bot_token, timeout=10):
        super().__init__()
        self.bot_token = bot_token
        self.timeout = timeout

    @Slot()
    def run(self):
        try:
            self.finished.emit(
                test_discord_bot_token(
                    self.bot_token,
                    timeout=self.timeout,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class ExtensionsDialog(QDialog):
    changed = Signal()
    def __init__(self, store: ExtensionStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.secret_store = SecretStore()
        self.current_id = ""
        self.current_credential_ref = ""
        self.current_preset_id = ""
        self.test_thread = None
        self.test_worker = None

        self.setWindowTitle("Extensions")
        self.resize(980, 700)
        self._build_ui()
        self._refresh_list()
        self._refresh_catalog()
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
        intro.setStyleSheet(muted_label_style())
        left.addWidget(intro)

        self.tabs = QTabWidget()

        installed_page = QWidget()
        installed_layout = QVBoxLayout(installed_page)
        installed_layout.setContentsMargins(0, 0, 0, 0)

        self.extension_list = QListWidget()
        self.extension_list.itemClicked.connect(self._extension_selected)
        installed_layout.addWidget(self.extension_list, 1)

        new_button = QPushButton("NEW EXTENSION")
        new_button.clicked.connect(self._new_extension)
        installed_layout.addWidget(new_button)

        catalog_page = QWidget()
        catalog_layout = QVBoxLayout(catalog_page)
        catalog_layout.setContentsMargins(0, 0, 0, 0)

        self.catalog_search = QLineEdit()
        self.catalog_search.setPlaceholderText("Search extensions...")
        self.catalog_search.textChanged.connect(self._refresh_catalog)
        catalog_layout.addWidget(self.catalog_search)

        self.catalog_category = QComboBox()
        self.catalog_category.addItem("All")
        for category in PRESET_CATEGORIES:
            self.catalog_category.addItem(category)
        self.catalog_category.currentIndexChanged.connect(self._refresh_catalog)
        catalog_layout.addWidget(self.catalog_category)

        self.catalog_list = QListWidget()
        self.catalog_list.itemClicked.connect(self._catalog_selected)
        catalog_layout.addWidget(self.catalog_list, 1)

        self.catalog_details = QLabel(
            "Select a preset to review its capabilities before adding it."
        )
        self.catalog_details.setWordWrap(True)
        self.catalog_details.setStyleSheet(muted_label_style(font_size=12))
        catalog_layout.addWidget(self.catalog_details)

        self.install_preset_button = QPushButton("ADD PRESET")
        self.install_preset_button.setEnabled(False)
        self.install_preset_button.clicked.connect(self._install_selected_preset)
        catalog_layout.addWidget(self.install_preset_button)

        self.tabs.addTab(installed_page, "INSTALLED")
        self.tabs.addTab(catalog_page, "CATALOG")
        left.addWidget(self.tabs, 1)
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
            "Secrets are stored in the operating-system credential store, not in registry.json."
        )
        auth_note.setWordWrap(True)
        auth_note.setStyleSheet("color:#7F8995;font-size:12px;")
        form.addRow("", auth_note)

        self.secret_label = QLabel("Discord Webhook URL")
        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_edit.setPlaceholderText("https://discord.com/api/webhooks/...")
        form.addRow(self.secret_label, self.secret_edit)

        secret_buttons = QHBoxLayout()
        self.save_secret_button = QPushButton("SAVE SECRET")
        self.save_secret_button.clicked.connect(self._save_secret)
        secret_buttons.addWidget(self.save_secret_button)
        self.clear_secret_button = QPushButton("CLEAR SECRET")
        self.clear_secret_button.clicked.connect(self._clear_secret)
        secret_buttons.addWidget(self.clear_secret_button)
        form.addRow("", secret_buttons)

        self.bot_guild_label = QLabel("Discord Guild ID")
        self.bot_guild_edit = QLineEdit()
        self.bot_guild_edit.setPlaceholderText("Server / Guild numeric ID")
        form.addRow(self.bot_guild_label, self.bot_guild_edit)

        self.bot_channel_label = QLabel("Discord Channel ID")
        self.bot_channel_edit = QLineEdit()
        self.bot_channel_edit.setPlaceholderText("Dedicated #localai channel numeric ID")
        form.addRow(self.bot_channel_label, self.bot_channel_edit)

        self.bot_user_label = QLabel("Allowed User ID")
        self.bot_user_edit = QLineEdit()
        self.bot_user_edit.setPlaceholderText("Only this Discord user may command LocalAI")
        form.addRow(self.bot_user_label, self.bot_user_edit)

        self.bot_model_label = QLabel("Bot Model")
        self.bot_model_edit = QLineEdit()
        self.bot_model_edit.setPlaceholderText("Blank = current LocalAI model when bot starts")
        form.addRow(self.bot_model_label, self.bot_model_edit)

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
        self.status_label.setStyleSheet(muted_label_style())
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

        self.send_test_message_button = QPushButton("SEND TEST MESSAGE")
        self.send_test_message_button.clicked.connect(self._send_discord_test_message)
        right.addWidget(self.send_test_message_button)

        note = QLabel(
            "Runtime execution is host-authorized per scope. Enabled state alone "
            "does not grant execution; the requested capability and host permission "
            "must also be allowed."
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

        if hasattr(self, "catalog_list"):
            self._refresh_catalog()

    def _refresh_catalog(self, *_args):
        if not hasattr(self, "catalog_list"):
            return

        selected_id = self.current_preset_id
        query = self.catalog_search.text() if hasattr(self, "catalog_search") else ""
        category = (
            self.catalog_category.currentText()
            if hasattr(self, "catalog_category")
            else "All"
        )

        self.catalog_list.clear()
        selected_row = -1

        for row, preset in enumerate(search_presets(query, category)):
            existing = self.store.find_by_preset_id(preset["id"])
            suffix = "  [INSTALLED]" if existing else ""
            item = QListWidgetItem(
                f"{preset['name']}  —  {preset['category']}{suffix}"
            )
            item.setData(Qt.UserRole, preset["id"])
            item.setToolTip(
                f"{preset['description']}\n"
                f"Capabilities: {', '.join(preset['capabilities'])}\n"
                f"Authentication: {preset['auth_type']}"
            )
            self.catalog_list.addItem(item)
            if preset["id"] == selected_id:
                selected_row = row

        if selected_row >= 0:
            self.catalog_list.setCurrentRow(selected_row)

    def _catalog_selected(self, item):
        preset_id = str(item.data(Qt.UserRole) or "")
        try:
            preset = find_preset(preset_id)
        except KeyError:
            return

        self.current_preset_id = preset_id
        self.catalog_details.setText(
            f"{preset['description']}\n"
            f"Capabilities: {', '.join(preset['capabilities'])}\n"
            f"Authentication: {preset['auth_type']}\n"
            f"Provider: {preset.get('provider_url') or 'not specified'}"
        )

        existing = self.store.find_by_preset_id(preset_id)
        self.install_preset_button.setEnabled(True)
        self.install_preset_button.setText(
            "OPEN INSTALLED" if existing else "ADD PRESET"
        )

    def _select_extension_id(self, extension_id):
        for row in range(self.extension_list.count()):
            item = self.extension_list.item(row)
            if str(item.data(Qt.UserRole) or "") == str(extension_id):
                self.extension_list.setCurrentRow(row)
                self._extension_selected(item)
                return True
        return False

    def _install_selected_preset(self):
        if not self.current_preset_id:
            return

        try:
            preset = find_preset(self.current_preset_id)
        except KeyError:
            return

        existing = self.store.find_by_preset_id(preset["id"])
        if existing is None:
            try:
                existing = self.store.save(preset_to_registry_entry(preset))
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Extension preset error",
                    str(exc),
                )
                return

        self._refresh_list(selected_id=existing["id"])
        self.tabs.setCurrentIndex(0)
        self._select_extension_id(existing["id"])
        self.status_label.setText(
            "Preset added. Configure its endpoint/credentials when support is available, "
            "then enable it explicitly."
        )
        self.changed.emit()

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
        self.current_credential_ref = ""
        self.secret_edit.clear()
        self.bot_guild_edit.clear()
        self.bot_channel_edit.clear()
        self.bot_user_edit.clear()
        self.bot_model_edit.clear()
        self._refresh_secret_controls()

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
        self.current_credential_ref = str(extension.get("credential_ref", "") or "")
        self.secret_edit.clear()
        config = dict(extension.get("config") or {})
        self.bot_guild_edit.setText(str(config.get("guild_id", "") or ""))
        self.bot_channel_edit.setText(str(config.get("channel_id", "") or ""))
        self.bot_user_edit.setText(str(config.get("allowed_user_id", "") or ""))
        self.bot_model_edit.setText(str(config.get("model", "") or ""))
        self._refresh_secret_controls(extension)

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
        config = {}
        if self.current_id:
            try:
                config = dict(self.store.get(self.current_id).get("config") or {})
            except Exception:
                config = {}

        if config.get("preset_id") == "discord-bot":
            config["guild_id"] = self.bot_guild_edit.text().strip()
            config["channel_id"] = self.bot_channel_edit.text().strip()
            config["allowed_user_id"] = self.bot_user_edit.text().strip()
            config["model"] = self.bot_model_edit.text().strip()

        return {
            "id": self.current_id,
            "name": self.name_edit.text(),
            "type": self.type_combo.currentData(),
            "endpoint": self.endpoint_edit.text(),
            "enabled": self.enabled_button.isChecked(),
            "auth_type": self.auth_combo.currentData(),
            "credential_ref": self.current_credential_ref,
            "capabilities": self.capabilities_edit.text(),
            "timeout": self.timeout_spin.value(),
            "config": config,
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
            self.changed.emit()
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
            if self.current_credential_ref:
                self.secret_store.delete_secret(self.current_credential_ref)
            self.store.delete(self.current_id)
        except Exception as exc:
            QMessageBox.critical(self, "Extension delete error", str(exc))
            return

        self.current_credential_ref = ""
        self.changed.emit()
        self._refresh_list()
        self._new_extension()

    @staticmethod
    def _is_discord_webhook(extension):
        config = dict((extension or {}).get("config") or {})
        return config.get("preset_id") == "discord-webhook"

    @staticmethod
    def _is_discord_bot(extension):
        config = dict((extension or {}).get("config") or {})
        return config.get("preset_id") == "discord-bot"

    def _refresh_secret_controls(self, extension=None):
        if extension is None and self.current_id:
            try:
                extension = self.store.get(self.current_id)
            except Exception:
                extension = None

        is_webhook = self._is_discord_webhook(extension or {})
        is_bot = self._is_discord_bot(extension or {})
        uses_secret = is_webhook or is_bot

        for widget in (
            self.secret_label,
            self.secret_edit,
            self.save_secret_button,
            self.clear_secret_button,
        ):
            widget.setVisible(uses_secret)

        self.send_test_message_button.setVisible(is_webhook)

        for widget in (
            self.bot_guild_label,
            self.bot_guild_edit,
            self.bot_channel_label,
            self.bot_channel_edit,
            self.bot_user_label,
            self.bot_user_edit,
            self.bot_model_label,
            self.bot_model_edit,
        ):
            widget.setVisible(is_bot)

        if uses_secret:
            has_secret = bool(self.current_credential_ref)
            self.clear_secret_button.setEnabled(has_secret)
            self.send_test_message_button.setEnabled(has_secret and is_webhook)
            if is_webhook:
                self.secret_label.setText("Discord Webhook URL")
                self.secret_edit.setPlaceholderText(
                    "Webhook URL saved securely"
                    if has_secret
                    else "https://discord.com/api/webhooks/..."
                )
            else:
                self.secret_label.setText("Discord Bot Token")
                self.secret_edit.setPlaceholderText(
                    "Bot token saved securely"
                    if has_secret
                    else "Paste Prometheusz bot token"
                )

    def _save_secret(self):
        if not self.current_id:
            self.status_label.setText("Save the extension before binding a secret.")
            return

        try:
            extension = self.store.get(self.current_id)
        except Exception as exc:
            self.status_label.setText(f"Extension load failed: {exc}")
            return

        is_webhook = self._is_discord_webhook(extension)
        is_bot = self._is_discord_bot(extension)
        if not (is_webhook or is_bot):
            self.status_label.setText("Secure secret binding is not enabled for this extension.")
            return

        try:
            if is_webhook:
                secret_value = validate_discord_webhook_url(self.secret_edit.text())
                credential_ref = f"extension:{self.current_id}:discord_webhook_url"
                success_text = "Discord webhook URL saved in the operating-system credential store."
            else:
                secret_value = validate_bot_token(self.secret_edit.text())
                credential_ref = f"extension:{self.current_id}:discord_bot_token"
                success_text = "Discord bot token saved in the operating-system credential store."

            self.secret_store.set_secret(credential_ref, secret_value)
            extension["credential_ref"] = credential_ref
            updated = self.store.save(extension)
        except Exception as exc:
            self.status_label.setText(f"Secret save failed: {exc}")
            return

        self.current_credential_ref = updated.get("credential_ref", "")
        self.secret_edit.clear()
        self.status_label.setText(success_text)
        self._refresh_secret_controls(updated)
        self.changed.emit()

    def _clear_secret(self):
        if not self.current_id or not self.current_credential_ref:
            return

        try:
            self.secret_store.delete_secret(self.current_credential_ref)
            extension = self.store.get(self.current_id)
            extension["credential_ref"] = ""
            updated = self.store.save(extension)
        except Exception as exc:
            self.status_label.setText(f"Secret clear failed: {exc}")
            return

        self.current_credential_ref = ""
        self.secret_edit.clear()
        self.status_label.setText("Secure Discord credential removed.")
        self._refresh_secret_controls(updated)
        self.changed.emit()

    def _discord_secret(self):
        if not self.current_credential_ref:
            raise ValueError("Save the Discord credential first.")
        secret = self.secret_store.get_secret(self.current_credential_ref)
        if not secret:
            raise ValueError("Saved Discord credential was not found.")
        return secret

    def _start_discord_worker(self, mode):
        if self.test_worker is not None:
            return

        extension = self._save_extension(silent=True)
        if extension is None:
            return

        try:
            webhook_url = self._discord_secret()
        except Exception as exc:
            self.status_label.setText(str(exc))
            return

        self.test_button.setEnabled(False)
        self.send_test_message_button.setEnabled(False)
        self.status_label.setText(
            "Sending Discord test message..."
            if mode == "send"
            else "Testing Discord webhook..."
        )

        self.test_thread = QThread(self)
        self.test_worker = DiscordWebhookWorker(
            webhook_url,
            mode=mode,
            timeout=extension.get("timeout", 10),
        )
        self.test_worker.moveToThread(self.test_thread)
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self._test_finished)
        self.test_worker.failed.connect(self._test_failed)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_worker.failed.connect(self.test_thread.quit)
        self.test_thread.finished.connect(self._cleanup_test_worker)
        self.test_thread.start()

    def _start_discord_bot_test(self, extension):
        if self.test_worker is not None:
            return

        try:
            token = self._discord_secret()
        except Exception as exc:
            self.status_label.setText(str(exc))
            return

        self.test_button.setEnabled(False)
        self.status_label.setText("Testing Prometheusz Discord bot token...")

        self.test_thread = QThread(self)
        self.test_worker = DiscordBotTestWorker(
            token,
            timeout=extension.get("timeout", 10),
        )
        self.test_worker.moveToThread(self.test_thread)
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.finished.connect(self._test_finished)
        self.test_worker.failed.connect(self._test_failed)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_worker.failed.connect(self.test_thread.quit)
        self.test_thread.finished.connect(self._cleanup_test_worker)
        self.test_thread.start()

    def _send_discord_test_message(self):
        if not self.current_id:
            return
        try:
            extension = self.store.get(self.current_id)
        except Exception:
            return
        if not self._is_discord_webhook(extension):
            return
        self._start_discord_worker("send")

    def _test_connection(self):
        if self.test_worker is not None:
            return

        extension = self._save_extension(silent=True)
        if extension is None:
            return

        if self._is_discord_webhook(extension):
            self._start_discord_worker("test")
            return
        if self._is_discord_bot(extension):
            self._start_discord_bot_test(extension)
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
        if hasattr(self, "send_test_message_button"):
            self.send_test_message_button.setEnabled(bool(self.current_credential_ref))

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
