from app import workers


class DummyClient:
    def __init__(self):
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        return "It may rain later. Data source: Open-Meteo."


def test_scheduled_worker_injects_authorized_weather_data(monkeypatch):
    monkeypatch.setattr(
        workers,
        "get_weather",
        lambda location: {
            "provider": "Open-Meteo",
            "location": {"name": location},
        },
    )
    monkeypatch.setattr(
        workers,
        "weather_context_text",
        lambda weather: "WEATHER TOOL DATA\nTemperature: 18 C",
    )

    client = DummyClient()
    task = {
        "id": "task-1",
        "name": "Weather",
        "prompt": "Tell me if rain is likely.",
        "model": "qwen-test",
        "location": "Bad Nenndorf",
        "permissions": {"weather": True},
    }

    completed = []
    failed = []
    worker = workers.ScheduledTaskWorker(client, task)
    worker.finished.connect(lambda task_id, text: completed.append((task_id, text)))
    worker.failed.connect(lambda task_id, text: failed.append((task_id, text)))
    worker.run()

    assert not failed
    assert completed == [
        ("task-1", "It may rain later. Data source: Open-Meteo.")
    ]
    assert client.calls
    model, messages = client.calls[0]
    assert model == "qwen-test"
    assert "AUTHORIZED TOOL DATA" in messages[-1]["content"]
    assert "WEATHER TOOL DATA" in messages[-1]["content"]


def test_scheduled_worker_fails_closed_without_permission():
    client = DummyClient()
    task = {
        "id": "task-2",
        "prompt": "Check something live.",
        "model": "qwen-test",
        "permissions": {"weather": False},
    }

    failed = []
    worker = workers.ScheduledTaskWorker(client, task)
    worker.failed.connect(lambda task_id, text: failed.append((task_id, text)))
    worker.run()

    assert failed
    assert failed[0][0] == "task-2"
    assert "no enabled data tool" in failed[0][1].lower()
    assert not client.calls
