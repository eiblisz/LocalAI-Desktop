import inspect

from app.chat_extensions_dialog import ChatExtensionsDialog


def test_chat_extensions_dialog_is_per_chat_and_persists_selection():
    build = inspect.getsource(ChatExtensionsDialog._build_ui)
    load = inspect.getsource(ChatExtensionsDialog._load_extensions)
    save = inspect.getsource(ChatExtensionsDialog._save)

    assert "ATTACH EXTENSIONS TO THIS CHAT" in build
    assert "Attachments are saved per chat" in build
    assert "self.chat_store.load(self.chat_id)" in load
    assert 'chat["attached_extensions"] = selected' in save
    assert "self.chat_store.save(chat)" in save
    assert "self.saved.emit(selected)" in save


def test_chat_extensions_dialog_shows_enabled_state_but_does_not_execute_tools():
    load = inspect.getsource(ChatExtensionsDialog._load_extensions)
    module_source = inspect.getsource(ChatExtensionsDialog)

    assert '"ENABLED" if enabled else "DISABLED"' in load
    assert "Capabilities:" in load
    assert "Chat runtime execution: not enabled yet" in load
    assert "requests." not in module_source
    assert "subprocess" not in module_source


def test_chat_extensions_dialog_drops_stale_deleted_extension_ids_on_save():
    load = inspect.getsource(ChatExtensionsDialog._load_extensions)
    selected = inspect.getsource(ChatExtensionsDialog._selected_ids)
    save = inspect.getsource(ChatExtensionsDialog._save)

    assert "installed_ids" in load
    assert "stale_count" in load
    assert "self.extension_list.count()" in selected
    assert "attached_extensions" in save


def test_chat_extensions_dialog_has_explicit_save_and_cancel_actions():
    build = inspect.getsource(ChatExtensionsDialog._build_ui)

    assert 'QPushButton("SAVE ATTACHMENTS")' in build
    assert 'QPushButton("CANCEL")' in build
    assert "save_button.clicked.connect(self._save)" in build
    assert "cancel_button.clicked.connect(self.reject)" in build
