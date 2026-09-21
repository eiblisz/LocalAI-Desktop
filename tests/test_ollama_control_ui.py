import inspect

from app.main_window import MainWindow
from app.vram_controller import (
    ACTION_EMERGENCY_KILL,
    ACTION_FREE_VRAM,
    ACTION_KILL_MODEL,
    ACTION_RESTART_OLLAMA,
    VramController,
)


def test_ollama_control_menu_contains_shared_runtime_actions():
    source = inspect.getsource(VramController.ensure_controls)

    assert ACTION_FREE_VRAM == "FREE VRAM"
    assert ACTION_KILL_MODEL == "KILL MODEL PROCESS"
    assert ACTION_RESTART_OLLAMA == "RESTART OLLAMA"
    assert ACTION_EMERGENCY_KILL == "EMERGENCY OLLAMA KILL"
    assert "combo.addItems" in source
    assert 'QPushButton("RUN")' in source


def test_free_vram_delegates_to_ownership_safe_release():
    source = inspect.getsource(VramController.release)

    assert "window.client.release_owned_models" in source
    assert "Shared Ollama resource" in source
    assert "FREE VRAM blocked" in source
    assert "release_ollama_vram" not in source


def test_kill_model_process_requires_authorized_pid_and_external_safety_check():
    source = inspect.getsource(VramController.kill_model_process)

    assert "owned_model_process_ids" in source
    assert "list_external_ollama_consumers" in inspect.getsource(
        VramController._external_consumers
    )
    assert "kill_ollama_model_processes(pids=pids)" in source
    assert "no ownership-authorized runner PID" in source


def test_restart_is_not_automatic_and_requires_shared_runtime_confirmation():
    source = inspect.getsource(VramController.restart)

    assert "foreign_active_leases" in source
    assert "QMessageBox.question" in source
    assert "Mas helyi AI folyamatokat is megszakithat." in source
    assert "restart_ollama()" in source


def test_emergency_global_kill_is_explicit_and_warned():
    source = inspect.getsource(VramController.emergency_kill_server)

    assert "QMessageBox.question" in source
    assert "Mas helyi AI folyamatokat is megszakithat." in source
    assert "kill_ollama()" in source
    assert "EMERGENCY OLLAMA KILL" in source


def test_desktop_uses_explicit_localai_ollama_owner():
    source = inspect.getsource(MainWindow.__init__)

    assert "self.ollama_owner_id" in source
    assert "auto_prepare_model=True" in source
    assert "owner_type=OWNER_LOCALAI_DESKTOP" in source
    assert "owner_id=self.ollama_owner_id" in source


def test_desktop_refresh_button_calls_full_refresh():
    build_source = inspect.getsource(MainWindow._build_ui)
    refresh_source = inspect.getsource(MainWindow._refresh_desktop)

    assert "self.refresh_models_button.clicked.connect(self._refresh_desktop)" in build_source
    assert "self._load_models()" in refresh_source
    assert "self._load_chat_list()" in refresh_source
    assert "self._refresh_resources()" in refresh_source
    assert "self._refresh_schedule_indicator()" in refresh_source
