import inspect

from app.main_window import MainWindow
from app.vram_controller import (
    ACTION_FREE_VRAM,
    ACTION_KILL_MODEL,
    ACTION_KILL_OLLAMA,
    ACTION_RESTART_OLLAMA,
    VramController,
)


def test_ollama_control_menu_contains_recovery_actions():
    source = inspect.getsource(VramController.ensure_controls)

    assert ACTION_FREE_VRAM == "FREE VRAM"
    assert ACTION_KILL_MODEL == "KILL MODEL PROCESS"
    assert ACTION_RESTART_OLLAMA == "RESTART OLLAMA"
    assert ACTION_KILL_OLLAMA == "KILL OLLAMA"
    assert "combo.addItems" in source
    assert 'QPushButton("RUN")' in source


def test_kill_model_process_stops_jobs_then_kills_runner():
    source = inspect.getsource(VramController.kill_model_process)

    assert "self._request_stop_active_jobs()" in source
    assert "kill_ollama_model_processes()" in source
    assert "window._refresh_desktop" in source


def test_restart_and_kill_ollama_are_explicit_actions():
    restart_source = inspect.getsource(VramController.restart)
    kill_source = inspect.getsource(VramController.kill_server)

    assert "restart_ollama()" in restart_source
    assert "kill_ollama()" in kill_source
    assert "self._request_stop_active_jobs()" in restart_source
    assert "self._request_stop_active_jobs()" in kill_source


def test_desktop_uses_auto_prepare_ollama_client():
    source = inspect.getsource(MainWindow.__init__)

    assert "OllamaClient(auto_prepare_model=True)" in source


def test_desktop_refresh_button_calls_full_refresh():
    build_source = inspect.getsource(MainWindow._build_ui)
    refresh_source = inspect.getsource(MainWindow._refresh_desktop)

    assert "self.refresh_models_button.clicked.connect(self._refresh_desktop)" in build_source
    assert "self._load_models()" in refresh_source
    assert "self._load_chat_list()" in refresh_source
    assert "self._refresh_resources()" in refresh_source
    assert "self._refresh_schedule_indicator()" in refresh_source
