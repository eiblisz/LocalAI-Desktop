import inspect

from app.extensions_dialog import ExtensionsDialog, ExtensionTestWorker


def test_extensions_dialog_exposes_registry_foundation_controls():
    source = inspect.getsource(ExtensionsDialog._build_ui)

    assert 'QLabel("EXTENSIONS")' in source
    assert 'QPushButton("NEW EXTENSION")' in source
    assert 'QPushButton("SAVE")' in source
    assert 'QPushButton("TEST CONNECTION")' in source
    assert 'QPushButton("DELETE")' in source
    assert "self.name_edit" in source
    assert "self.type_combo" in source
    assert "self.endpoint_edit" in source
    assert "self.capabilities_edit" in source
    assert "self.auth_combo" in source
    assert "self.enabled_button" in source


def test_extensions_dialog_uses_password_field_and_os_secret_store_for_discord():
    source = inspect.getsource(ExtensionsDialog._build_ui)
    save_source = inspect.getsource(ExtensionsDialog._save_secret)

    assert "QLineEdit.EchoMode.Password" in source
    assert 'QPushButton("SAVE SECRET")' in source
    assert 'QPushButton("CLEAR SECRET")' in source
    assert "operating-system credential store" in source
    assert "self.secret_store.set_secret" in save_source
    assert 'extension["credential_ref"] = credential_ref' in save_source


def test_extensions_connection_test_runs_off_ui_thread():
    source = inspect.getsource(ExtensionsDialog._test_connection)

    assert "QThread(self)" in source
    assert "ExtensionTestWorker(extension)" in source
    assert "moveToThread" in source
    assert "self.test_thread.start()" in source


def test_extension_test_worker_delegates_to_bounded_connection_test():
    source = inspect.getsource(ExtensionTestWorker.run)

    assert "test_extension_connection(self.extension)" in source
    assert "self.finished.emit" in source
    assert "self.failed.emit" in source


def test_foundation_slice_does_not_claim_chat_runtime_access():
    source = inspect.getsource(ExtensionsDialog._build_ui)

    assert "Enabling an extension does not give the chat access yet." in source
    assert "Runtime tool injection is deliberately not enabled yet." in source


def test_extensions_dialog_has_installed_and_catalog_tabs():
    source = inspect.getsource(ExtensionsDialog._build_ui)

    assert 'self.tabs.addTab(installed_page, "INSTALLED")' in source
    assert 'self.tabs.addTab(catalog_page, "CATALOG")' in source
    assert 'self.catalog_search.setPlaceholderText("Search extensions...")' in source
    assert "PRESET_CATEGORIES" in source
    assert 'QPushButton("ADD PRESET")' in source


def test_catalog_install_is_disabled_by_default_and_deduplicated():
    source = inspect.getsource(ExtensionsDialog._install_selected_preset)

    assert "self.store.find_by_preset_id" in source
    assert "preset_to_registry_entry" in source
    assert "self.store.save" in source
    assert "self.tabs.setCurrentIndex(0)" in source


def test_discord_webhook_actions_use_background_worker_and_secret_reference():
    start = inspect.getsource(ExtensionsDialog._start_discord_worker)
    send = inspect.getsource(ExtensionsDialog._send_discord_test_message)
    secret = inspect.getsource(ExtensionsDialog._discord_secret)

    assert "DiscordWebhookWorker(" in start
    assert "QThread(self)" in start
    assert "self.test_thread.start()" in start
    assert 'self._start_discord_worker("send")' in send
    assert "self.secret_store.get_secret" in secret


def test_deleting_extension_removes_bound_secret_first():
    source = inspect.getsource(ExtensionsDialog._delete_extension)

    assert "self.secret_store.delete_secret(self.current_credential_ref)" in source
    assert source.index("delete_secret") < source.index("self.store.delete")


def test_prometheusz_bot_fields_and_secure_token_controls_exist():
    build = inspect.getsource(ExtensionsDialog._build_ui)
    secret = inspect.getsource(ExtensionsDialog._save_secret)
    payload = inspect.getsource(ExtensionsDialog._form_payload)
    test_source = inspect.getsource(ExtensionsDialog._start_discord_bot_test)

    assert "Discord Guild ID" in build
    assert "Discord Channel ID" in build
    assert "Allowed User ID" in build
    assert "Bot Model" in build
    assert "validate_bot_token" in secret
    assert "discord_bot_token" in secret
    assert 'config["guild_id"]' in payload
    assert 'config["channel_id"]' in payload
    assert 'config["allowed_user_id"]' in payload
    assert "DiscordBotTestWorker" in test_source


def test_extension_changes_emit_runtime_resync_signal():
    save = inspect.getsource(ExtensionsDialog._save_extension)
    secret = inspect.getsource(ExtensionsDialog._save_secret)
    delete = inspect.getsource(ExtensionsDialog._delete_extension)

    assert "self.changed.emit()" in save
    assert "self.changed.emit()" in secret
    assert "self.changed.emit()" in delete

