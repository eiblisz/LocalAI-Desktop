from types import SimpleNamespace

import requests

from app.vram_release import release_ollama_vram


class _Response:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_release_vram_unloads_all_running_ollama_models(monkeypatch):
    posts = []

    def fake_get(url, timeout):
        assert url == "http://127.0.0.1:11434/api/ps"
        assert timeout <= 5.0
        return _Response({
            "models": [
                {"name": "qwen3-coder:30b-a3b-q8_0"},
                {"name": "image-model:latest"},
            ]
        })

    def fake_post(url, json, timeout):
        posts.append((url, json, timeout))
        return _Response()

    monkeypatch.setattr("app.vram_release.requests.get", fake_get)
    monkeypatch.setattr("app.vram_release.requests.post", fake_post)

    client = SimpleNamespace(base_url="http://127.0.0.1:11434")
    released = release_ollama_vram(client, fallback_model="ignored")

    assert released == [
        "qwen3-coder:30b-a3b-q8_0",
        "image-model:latest",
    ]
    assert [item[1]["model"] for item in posts] == released
    assert all(item[1]["keep_alive"] == 0 for item in posts)
    assert all(item[1]["prompt"] == "" for item in posts)
    assert all(item[1]["stream"] is False for item in posts)


def test_release_vram_falls_back_to_selected_model_when_ps_fails(monkeypatch):
    posts = []

    def fake_get(url, timeout):
        raise requests.ConnectionError("ps unavailable")

    def fake_post(url, json, timeout):
        posts.append(json)
        return _Response()

    monkeypatch.setattr("app.vram_release.requests.get", fake_get)
    monkeypatch.setattr("app.vram_release.requests.post", fake_post)

    client = SimpleNamespace(base_url="http://127.0.0.1:11434")
    released = release_ollama_vram(
        client,
        fallback_model="qwen3-coder:30b-a3b-q8_0",
    )

    assert released == ["qwen3-coder:30b-a3b-q8_0"]
    assert posts == [{
        "model": "qwen3-coder:30b-a3b-q8_0",
        "prompt": "",
        "stream": False,
        "keep_alive": 0,
    }]
