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
