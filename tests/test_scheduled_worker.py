from app import workers


class DummyClient:
    def __init__(self):
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        return "Scheduled result."


def _run_worker(task):
    client = DummyClient()
    completed = []
    failed = []
    worker = workers.ScheduledTaskWorker(client, task)
    worker.finished.connect(lambda task_id, text: completed.append((task_id, text)))
    worker.failed.connect(lambda task_id, text: failed.append((task_id, text)))
    worker.run()
    return client, completed, failed


def test_scheduled_worker_injects_weather_data(monkeypatch):
    monkeypatch.setattr(
        workers,
        "get_weather",
        lambda location: {"provider": "Open-Meteo", "location": {"name": location}},
    )
    monkeypatch.setattr(
        workers,
        "weather_context_text",
        lambda weather: "WEATHER TOOL DATA\nTemperature: 18 C",
    )

    client, completed, failed = _run_worker({
        "id": "weather-1",
        "task_type": "weather",
        "prompt": "Tell me if rain is likely.",
        "model": "qwen-test",
        "location": "Bad Nenndorf",
    })

    assert not failed
    assert completed == [("weather-1", "Scheduled result.")]
    assert "WEATHER TOOL DATA" in client.calls[0][1][-1]["content"]


def test_scheduled_worker_injects_ebay_results(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_ebay",
        lambda query, max_results=8: {
            "provider": "eBay.de public search",
            "query": query,
            "results": [{"title": "RAM kit", "price": "100 EUR"}],
        },
    )
    monkeypatch.setattr(
        workers,
        "ebay_context_text",
        lambda payload: "EBAY SEARCH TOOL DATA\nRAM kit | 100 EUR",
    )

    client, completed, failed = _run_worker({
        "id": "ebay-1",
        "task_type": "ebay",
        "prompt": "Summarize interesting offers.",
        "model": "qwen-test",
        "ebay_query": "64GB DDR4",
        "ebay_max_results": 5,
    })

    assert not failed
    assert completed
    assert "EBAY SEARCH TOOL DATA" in client.calls[0][1][-1]["content"]


def test_scheduled_worker_injects_computer_status(monkeypatch):
    monkeypatch.setattr(
        workers,
        "get_computer_status",
        lambda: {"cpu_percent": 42},
    )
    monkeypatch.setattr(
        workers,
        "computer_status_context_text",
        lambda payload: "COMPUTER STATUS TOOL DATA\nCPU usage: 42%",
    )

    client, completed, failed = _run_worker({
        "id": "computer-1",
        "task_type": "computer",
        "prompt": "Tell me if the PC needs attention.",
        "model": "qwen-test",
    })

    assert not failed
    assert completed
    assert "COMPUTER STATUS TOOL DATA" in client.calls[0][1][-1]["content"]


def test_custom_scheduled_worker_has_no_live_tool_context():
    client, completed, failed = _run_worker({
        "id": "custom-1",
        "task_type": "custom",
        "prompt": "Write a short reminder.",
        "model": "qwen-test",
    })

    assert not failed
    assert completed
    user_message = client.calls[0][1][-1]["content"]
    assert "AUTHORIZED TOOL DATA" not in user_message
    assert "SCHEDULED TASK TYPE: custom" in user_message


def test_unknown_scheduled_task_type_fails_closed():
    client, completed, failed = _run_worker({
        "id": "bad-1",
        "task_type": "unknown",
        "prompt": "Do something.",
        "model": "qwen-test",
    })

    assert not completed
    assert failed
    assert "unsupported scheduled task type" in failed[0][1].lower()
    assert not client.calls


def test_custom_scheduled_worker_can_use_web_search(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "DuckDuckGo HTML",
            "query": query,
            "results": [{"title": "Fresh result"}],
        },
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA\nFresh result",
    )

    client, completed, failed = _run_worker({
        "id": "custom-web-1",
        "task_type": "custom",
        "prompt": "Summarize current AI news.",
        "model": "qwen-test",
        "web_search_enabled": True,
        "web_query": "AI news",
        "web_max_results": 5,
        "web_fetch_pages": True,
    })

    assert not failed
    assert completed
    assert "WEB SEARCH TOOL DATA" in client.calls[0][1][-1]["content"]


def test_custom_web_search_falls_back_to_prompt_for_query(monkeypatch):
    seen = {}

    def fake_search(query, max_results=6, fetch_pages=True):
        seen["query"] = query
        return {"provider": "DuckDuckGo HTML", "query": query, "results": []}

    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    _client, completed, failed = _run_worker({
        "id": "custom-web-2",
        "task_type": "custom",
        "prompt": "latest local AI developments",
        "model": "qwen-test",
        "web_search_enabled": True,
        "web_query": "",
    })

    assert not failed
    assert completed
    assert seen["query"] == "latest local AI developments"
