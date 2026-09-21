import os
import pytest

from app.ollama_client import OllamaClient
from app.ollama_resource_coordinator import (
    OWNER_EINSTEIN,
    OWNER_LOCALAI_DESKTOP,
    STATE_IDLE,
    STATE_INFERENCE_ACTIVE,
    STATE_STALE,
    OllamaResourceBusyError,
    ResourceLeaseStore,
)


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "ok"}}


def test_chat_once_forwards_explicit_native_response_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "string"}},
    }

    result = OllamaClient("http://127.0.0.1:11434").chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
        response_format=schema,
    )

    assert result == "ok"
    assert captured["json"] == {
        "model": "qwen-test",
        "messages": [{"role": "user", "content": "test"}],
        "stream": False,
        "format": schema,
    }
    assert captured["timeout"] == 600.0


def test_chat_once_omits_format_when_not_explicitly_selected(monkeypatch):
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    OllamaClient().chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )

    assert "format" not in captured["json"]


def _desktop_client(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    return OllamaClient(
        owner_type=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        resource_store=store,
    ), store


def test_prepare_model_unloads_only_proven_desktop_owned_idle_model(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)
    released = []

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="gemma4:26b",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["gemma4:26b", "qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 777, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda _client, model, timeout: released.append(model),
    )

    result = client.prepare_model("qwen3-coder:30b-a3b-q8_0")

    assert result == ["gemma4:26b"]
    assert released == ["gemma4:26b"]
    assert store.ownership("gemma4:26b")["state"] == STATE_STALE


def test_prepare_model_blocks_foreign_active_owner(monkeypatch, tmp_path):
    client, store = _desktop_client(tmp_path)
    released = []

    store.upsert(
        owner=OWNER_EINSTEIN,
        owner_id="einstein:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_INFERENCE_ACTIVE,
        owner_pid=None,
        model_pid=888,
    )

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 888, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda _client, model, timeout: released.append(model),
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "EINSTEIN" in str(exc.value)
    assert released == []


def test_prepare_model_blocks_unknown_ownership(monkeypatch, tmp_path):
    client, _store = _desktop_client(tmp_path)

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 999, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "UNKNOWN" in str(exc.value)


def test_prepare_model_reconciles_stopping_without_process_kill(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)
    unloaded = []

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(client, "_runner_processes", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda *_args, **_kwargs: unloaded.append(True),
    )

    assert client.prepare_model("gemma4:26b") == []
    assert unloaded == []
    ownership = store.ownership("qwen3-coder:30b-a3b-q8_0")
    assert ownership["state"] == STATE_STALE
    assert "no runner process" in ownership["detail"]


def test_prepare_model_blocks_when_external_consumer_is_visible(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 777, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{"pid": 901, "owner": "MANUAL"}],
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "MANUAL" in str(exc.value)


def test_auto_prepare_model_is_opt_in_for_chat_once(monkeypatch):
    captured = {"prepared": []}

    def fake_prepare(self, model, timeout=6.0):
        captured["prepared"].append(model)
        return []

    def fake_post(_url, **_kwargs):
        return _Response()

    monkeypatch.setattr(OllamaClient, "prepare_model", fake_prepare)
    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    OllamaClient(auto_prepare_model=False).chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )
    assert captured["prepared"] == []

    OllamaClient(auto_prepare_model=True).chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )
    assert captured["prepared"] == ["qwen-test"]



def test_automatic_model_prepare_has_no_process_kill_or_server_restart_path():
    import inspect

    source = inspect.getsource(OllamaClient.prepare_model)

    assert "kill_ollama" not in source
    assert "kill_ollama_model_processes" not in source
    assert "restart_ollama" not in source
    assert "unload_ollama_model" in source
    assert "can_control_model" in source



def test_prepare_model_blocks_manual_other_model_before_api_ps(monkeypatch, tmp_path):
    client, _store = _desktop_client(tmp_path)
    touched = {"ps": False}

    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{
            "pid": 901,
            "owner": "MANUAL",
            "model": "qwen3-coder:30b-a3b-q8_0",
        }],
    )

    def should_not_read_ps(_client, timeout):
        touched["ps"] = True
        raise AssertionError("/api/ps must not be trusted before visible external client safety")

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        should_not_read_ps,
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "MANUAL" in str(exc.value)
    assert "qwen3-coder:30b-a3b-q8_0" in str(exc.value)
    assert touched["ps"] is False


def test_prepare_model_allows_visible_manual_client_only_for_same_target(
    monkeypatch,
    tmp_path,
):
    client, _store = _desktop_client(tmp_path)

    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{
            "pid": 901,
            "owner": "MANUAL",
            "model": "qwen3-coder:30b-a3b-q8_0",
        }],
    )
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )

    assert client.prepare_model("qwen3-coder:30b-a3b-q8_0") == []
