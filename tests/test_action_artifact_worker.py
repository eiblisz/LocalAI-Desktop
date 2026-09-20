from pathlib import Path

from app.artifact_service import ArtifactPlanItem, ArtifactRequest
from app.workers import (
    ArtifactActionWorker,
    grounded_artifact_unsupported_tokens,
)


class FakeClient:
    def __init__(self, answer="# Report\n\nGenerated content"):
        self.answer = answer
        self.calls = []

    def chat_once(self, model, messages):
        self.calls.append((model, messages))
        return self.answer


def test_artifact_action_worker_creates_all_planned_outputs(tmp_path, monkeypatch):
    import app.workers as workers_module

    created = []

    def fake_create_artifact(fmt, **kwargs):
        path = tmp_path / f"output.{fmt if fmt != 'summary' else 'md'}"
        path.write_text(kwargs["content"], encoding="utf-8")
        created.append((fmt, kwargs, path))
        return path

    monkeypatch.setattr(workers_module, "create_artifact", fake_create_artifact)

    client = FakeClient()
    plans = [
        ArtifactPlanItem(
            prompt="Készíts PDF riportot.",
            request=ArtifactRequest("pdf", "Red Executive"),
        ),
        ArtifactPlanItem(
            prompt="Készíts HTML riportot.",
            request=ArtifactRequest("html", "Classic Professional"),
        ),
    ]
    worker = ArtifactActionWorker(
        client,
        "qwen-test",
        [{"role": "user", "content": "create reports"}],
        "Készíts két riportot.",
        plans,
    )
    results = []
    errors = []
    worker.finished.connect(results.extend)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == []
    assert [item["format"] for item in results] == ["pdf", "html"]
    assert [item[0] for item in created] == ["pdf", "html"]
    assert all(Path(item["path"]).exists() for item in results)


def test_web_grounded_artifact_uses_verified_source_context(tmp_path, monkeypatch):
    import app.workers as workers_module

    monkeypatch.setattr(
        workers_module,
        "run_chat_web_request",
        lambda *args, **kwargs: (
            "Verified current Ollama version is 9.9.9. "
            "Source: https://example.com/ollama"
        ),
    )

    captured = {}

    def fake_create_artifact(fmt, **kwargs):
        captured.update(kwargs)
        path = tmp_path / "ollama.html"
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    monkeypatch.setattr(workers_module, "create_artifact", fake_create_artifact)

    class GroundedClient(FakeClient):
        def chat_once(self, model, messages):
            joined = "\n".join(
                str(item.get("content") or "")
                for item in messages
            )
            assert "VERIFIED WEB RESEARCH SOURCE" in joined
            assert "9.9.9" in joined
            return "# Ollama\n\nCurrent version: 9.9.9"

    worker = ArtifactActionWorker(
        GroundedClient(),
        "qwen-test",
        [{"role": "user", "content": "latest Ollama"}],
        "Mi a legújabb Ollama verzió, és készíts HTML riportot.",
        [
            ArtifactPlanItem(
                prompt="Készíts HTML riportot a legújabb Ollama verzióról.",
                request=ArtifactRequest("html", "Red Professional"),
            )
        ],
        use_web=True,
    )
    results = []
    errors = []
    worker.finished.connect(results.extend)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == []
    assert len(results) == 1
    assert "9.9.9" in captured["content"]
    assert "VERIFIED WEB RESEARCH SOURCE" in captured["source_text"]


def test_grounded_artifact_guard_detects_invented_version_and_url():
    unsupported = grounded_artifact_unsupported_tokens(
        "Ollama 195.6. Source: https://fake.example/version",
        (
            "Latest Ollama version is 0.34.2. "
            "Source: https://ollama.com/download"
        ),
    )

    assert "195.6" in unsupported
    assert "https://fake.example/version" in unsupported
    assert "0.34.2" not in unsupported


def test_grounded_artifact_repairs_unsupported_version_before_write(
    tmp_path,
    monkeypatch,
):
    import app.workers as workers_module

    monkeypatch.setattr(
        workers_module,
        "run_chat_web_request",
        lambda *args, **kwargs: (
            "According to the official source, the latest Ollama version "
            "is 0.34.2. Source: https://ollama.com/download"
        ),
    )

    written = []

    def fake_create_artifact(fmt, **kwargs):
        written.append(kwargs["content"])
        path = tmp_path / "ollama.html"
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    monkeypatch.setattr(
        workers_module,
        "create_artifact",
        fake_create_artifact,
    )

    class RepairingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.responses = [
                "# Ollama 195.6\n\nLatest version: 195.6",
                "# Ollama\n\nLatest version: 0.34.2",
            ]

        def chat_once(self, model, messages):
            self.calls.append((model, messages))
            return self.responses.pop(0)

    worker = ArtifactActionWorker(
        RepairingClient(),
        "qwen-test",
        [{"role": "user", "content": "latest Ollama"}],
        "Mi a legújabb Ollama verzió, és készíts HTML riportot.",
        [
            ArtifactPlanItem(
                prompt="Készíts HTML riportot a legújabb Ollama verzióról.",
                request=ArtifactRequest("html", "Red Professional"),
            )
        ],
        use_web=True,
    )
    results = []
    errors = []
    worker.finished.connect(results.extend)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == []
    assert len(results) == 1
    assert written == ["# Ollama\n\nLatest version: 0.34.2"]


def test_grounded_artifact_fails_closed_after_repair_still_invents_fact(
    tmp_path,
    monkeypatch,
):
    import app.workers as workers_module

    monkeypatch.setattr(
        workers_module,
        "run_chat_web_request",
        lambda *args, **kwargs: (
            "Latest Ollama version is 0.34.2. "
            "Source: https://ollama.com/download"
        ),
    )

    writes = []
    monkeypatch.setattr(
        workers_module,
        "create_artifact",
        lambda *args, **kwargs: writes.append(kwargs) or (tmp_path / "bad.html"),
    )

    class HallucinatingClient(FakeClient):
        def chat_once(self, model, messages):
            self.calls.append((model, messages))
            return "# Ollama 195.6\n\nLatest version: 195.6"

    worker = ArtifactActionWorker(
        HallucinatingClient(),
        "qwen-test",
        [{"role": "user", "content": "latest Ollama"}],
        "Mi a legújabb Ollama verzió, és készíts HTML riportot.",
        [
            ArtifactPlanItem(
                prompt="Készíts HTML riportot a legújabb Ollama verzióról.",
                request=ArtifactRequest("html", "Red Professional"),
            )
        ],
        use_web=True,
    )
    results = []
    errors = []
    worker.finished.connect(results.extend)
    worker.failed.connect(errors.append)

    worker.run()

    assert results == []
    assert writes == []
    assert len(errors) == 1
    assert "unsupported factual literals" in errors[0]
    assert "195.6" in errors[0]
