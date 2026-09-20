from pathlib import Path

from app.artifact_service import ArtifactPlanItem, ArtifactRequest
from app.workers import ArtifactActionWorker


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
