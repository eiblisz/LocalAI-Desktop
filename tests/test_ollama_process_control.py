from types import SimpleNamespace

import pytest

import app.ollama_process_control as control


def test_kill_model_process_requires_explicit_authorized_pids(monkeypatch):
    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    with pytest.raises(control.OllamaProcessControlError):
        control.kill_ollama_model_processes()


def test_kill_model_process_targets_only_authorized_runner_pids(monkeypatch):
    captured = {}

    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="101,202", stderr="")

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    assert control.kill_ollama_model_processes(pids=[101, 202]) == [101, 202]

    script = captured["command"][-1]
    assert "$authorized = @(101,202)" in script
    assert "runner" in script
    assert "ollama_llama_server.exe" in script
    assert "Stop-Process" in script


def test_list_model_processes_is_read_only_discovery(monkeypatch):
    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='[{"ProcessId":501,"Name":"ollama_llama_server.exe","CommandLine":"runner"}]',
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    rows = control.list_ollama_model_processes()
    assert rows == [
        {
            "pid": 501,
            "name": "ollama_llama_server.exe",
            "command_line": "runner",
        }
    ]


def test_external_consumer_discovery_classifies_manual_and_einstein(monkeypatch):
    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '[{"ProcessId":601,"Name":"ollama.exe","CommandLine":"ollama run gemma4:26b"},'
                '{"ProcessId":602,"Name":"python.exe","CommandLine":"python C:\\\\EinsteinAI\\\\main.py"}]'
            ),
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    rows = control.list_external_ollama_consumers()
    assert [row["owner"] for row in rows] == ["MANUAL", "EINSTEIN"]


def test_kill_ollama_targets_server_and_runner_for_emergency_action(monkeypatch):
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



def test_direct_http_consumer_is_other_and_current_pid_can_be_excluded(monkeypatch):
    captured = {}
    monkeypatch.setattr(control.os, "name", "nt", raising=False)

    def fake_run(command, **kwargs):
        captured["script"] = command[-1]
        return SimpleNamespace(
            returncode=0,
            stdout='{"ProcessId":701,"Name":"python.exe","CommandLine":"python C:\\\\OtherAI\\\\client.py"}',
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", fake_run)

    rows = control.list_external_ollama_consumers()
    assert rows[0]["owner"] == "OTHER"
    assert "Get-NetTCPConnection -RemotePort 11434" in captured["script"]

    excluded = control.list_external_ollama_consumers(exclude_pids=[701])
    assert excluded == []
