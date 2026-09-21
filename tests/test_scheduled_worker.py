from app import workers


class DummyClient:
    def __init__(self):
        self.calls = []
        self.releases = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        return "Scheduled result."

    def release_owned_models(self, timeout=5.0):
        self.releases.append(timeout)
        return {"released": ["qwen-test"], "blocked": [], "reconciled": []}


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


def test_custom_web_search_generates_targeted_query_when_blank(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        workers.ScheduledTaskWorker,
        "_generate_search_query",
        lambda self, prompt, model: "local AI models Ollama Qwen news",
    )

    def fake_search(query, max_results=6, fetch_pages=True):
        seen["query"] = query
        return {
            "provider": "Bing Web RSS",
            "query": query,
            "results": [{
                "title": "Qwen local model update",
                "url": "https://example.com/qwen",
                "snippet": "Fresh local AI model news",
            }],
        }

    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA\nQwen update",
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/qwen"],
    )

    _client, completed, failed = _run_worker({
        "id": "custom-web-2",
        "task_type": "custom",
        "prompt": "Keresd meg a legfrissebb fontos híreket a lokális AI modellekről.",
        "model": "qwen-test",
        "web_search_enabled": True,
        "web_query": "",
    })

    assert not failed
    assert completed
    assert seen["query"] == "local AI models Ollama Qwen news"
    assert "Search query: local AI models Ollama Qwen news" in completed[0][1]
    assert "https://example.com/qwen" in completed[0][1]


def test_ebay_generic_query_uses_task_prompt(monkeypatch):
    seen = {}

    def fake_search(query, max_results=8):
        seen["query"] = query
        return {
            "provider": "test",
            "query": query,
            "results": [{"title": "GPU", "url": "https://www.ebay.de/itm/1"}],
        }

    monkeypatch.setattr(workers, "search_ebay", fake_search)
    monkeypatch.setattr(
        workers,
        "ebay_context_text",
        lambda payload: "EBAY SEARCH TOOL DATA",
    )

    _client, completed, failed = _run_worker({
        "id": "ebay-generic",
        "task_type": "ebay",
        "prompt": "keress 32gb-os videokartyat mindegy melyik tipus",
        "model": "qwen-test",
        "ebay_query": "Ebay",
        "ebay_max_results": 9,
    })

    assert not failed
    assert completed
    assert seen["query"] == "keress 32gb-os videokartyat mindegy melyik tipus"


def test_web_result_system_prompt_requires_source_grounding(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Bing Web RSS",
            "query": query,
            "results": [{
                "title": "Relevant result",
                "url": "https://example.com/relevant",
                "snippet": "Relevant source data",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA\nRelevant source data",
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/relevant"],
    )

    client, completed, failed = _run_worker({
        "id": "grounded-1",
        "task_type": "custom",
        "prompt": "Summarize current local AI news.",
        "model": "qwen-test",
        "web_search_enabled": True,
        "web_query": "local AI Qwen news",
    })

    assert not failed
    system = client.calls[-1][1][0]["content"]
    assert "use ONLY the AUTHORIZED TOOL DATA" in system
    assert "no relevant sources were found" in system
    assert "Never invent scores, ratings, prices" in system
    assert "https://example.com/relevant" in completed[0][1]



def test_scheduled_worker_releases_scheduler_owned_model_after_task():
    client, completed, failed = _run_worker({
        "id": "release-1",
        "task_type": "custom",
        "prompt": "Short scheduled task.",
        "model": "qwen-test",
    })

    assert not failed
    assert completed
    assert client.releases == [5.0]
