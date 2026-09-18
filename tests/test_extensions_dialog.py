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


def test_extensions_dialog_does_not_collect_raw_secrets():
    source = inspect.getsource(ExtensionsDialog._build_ui).lower()

    assert "api key:" not in source
    assert "password_edit" not in source
    assert "token_edit" not in source
    assert "secret_edit" not in source
    assert "credentials are intentionally not stored here" in source


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
