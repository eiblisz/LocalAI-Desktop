from app.ollama_client import OllamaClient


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


def test_prepare_model_unloads_only_stale_models(monkeypatch):
    client = OllamaClient()
    released = []

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["gemma3:latest", "qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda _client, model, timeout: released.append(model),
    )

    result = client.prepare_model("qwen3-coder:30b-a3b-q8_0")

    assert result == ["gemma3:latest"]
    assert released == ["gemma3:latest"]


def test_prepare_model_kills_runner_when_unload_is_stuck(monkeypatch):
    import requests

    client = OllamaClient()
    killed = []

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["gemma3:latest"],
    )

    def fail_unload(_client, _model, timeout):
        raise requests.Timeout("stuck runner")

    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        fail_unload,
    )
    monkeypatch.setattr(
        "app.ollama_client.kill_ollama_model_processes",
        lambda timeout: killed.append(timeout) or [1234],
    )

    assert client.prepare_model("qwen3-coder:30b-a3b-q8_0") == []
    assert killed


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
