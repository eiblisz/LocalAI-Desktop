from types import SimpleNamespace

import app.ollama_process_control as control


def test_kill_model_process_targets_runner_without_server(monkeypatch):
    captured = {}

    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="101,202", stderr="")

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    assert control.kill_ollama_model_processes() == [101, 202]

    script = captured["command"][-1]
    assert "runner" in script
    assert "ollama_llama_server.exe" in script
    assert "Stop-Process" in script


def test_kill_ollama_targets_server_and_runner(monkeypatch):
    captured = {}

    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        captured["script"] = command[-1]
        return SimpleNamespace(returncode=0, stdout="303", stderr="")

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    assert control.kill_ollama() == [303]
    assert "ollama.exe" in captured["script"]
    assert "ollama_llama_server.exe" in captured["script"]
    assert "ollama app.exe" in captured["script"]


def test_start_ollama_uses_path_executable_and_returns_pid(monkeypatch):
    process = SimpleNamespace(pid=404, returncode=None)
    process.poll = lambda: None
    captured = {}

    monkeypatch.setattr(control.shutil, "which", lambda name: r"C:\Ollama\ollama.exe")
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(control.subprocess, "Popen", fake_popen)

    assert control.start_ollama(timeout=0.1) == 404
    assert captured["command"] == [r"C:\Ollama\ollama.exe", "serve"]


def test_restart_ollama_kills_then_starts(monkeypatch):
    events = []

    monkeypatch.setattr(
        control,
        "kill_ollama",
        lambda timeout=8.0: events.append("kill") or [1, 2],
    )
    monkeypatch.setattr(control.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        control,
        "start_ollama",
        lambda timeout=8.0: events.append("start") or 909,
    )

    result = control.restart_ollama()

    assert events == ["kill", "start"]
    assert result == {"killed": [1, 2], "started_pid": 909}
