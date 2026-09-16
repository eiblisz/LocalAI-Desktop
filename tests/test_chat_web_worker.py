from app import workers


class DummyWebClient:
    def __init__(self):
        self.once_calls = []
        self.stream_calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.once_calls.append((model, messages))
        return "Qwen local AI latest news"

    def chat_stream(
        self,
        model,
        messages,
        on_token,
        should_stop,
        timeout=600.0,
    ):
        self.stream_calls.append((model, messages))
        if not should_stop():
            on_token("Grounded web answer.")


def test_chat_web_worker_searches_streams_and_appends_sources(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "Bing Web RSS",
            "query": query,
            "results": [{
                "title": "Qwen update",
                "url": "https://example.com/qwen",
                "snippet": "Fresh Qwen local AI news",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/qwen"],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA\nQwen update",
    )

    client = DummyWebClient()
    tokens = []
    failed = []
    finished = []

    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress ra a legfrissebb Qwen hirekre"},
        ],
        "Keress ra a legfrissebb Qwen hirekre",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()

    assert not failed
    assert finished == [True]
    assert client.once_calls
    assert client.stream_calls

    streamed_messages = client.stream_calls[0][1]
    assert "use ONLY the AUTHORIZED WEB TOOL DATA" in streamed_messages[1]["content"]
    assert "AUTHORIZED WEB TOOL DATA" in streamed_messages[-1]["content"]

    combined = "".join(tokens)
    assert "Grounded web answer." in combined
    assert "Search query: Qwen local AI latest news" in combined
    assert "https://example.com/qwen" in combined


def test_chat_web_worker_fails_closed_without_sources(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [],
        },
    )
    monkeypatch.setattr(workers, "source_urls", lambda payload: [])
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "",
    )

    client = DummyWebClient()
    failed = []

    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem valamit az interneten",
    )
    worker.failed.connect(failed.append)
    worker.run()

    assert failed
    assert "no usable public sources" in failed[0].lower()
    assert not client.stream_calls


def test_chat_web_worker_stop_prevents_source_footer(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Result",
                "url": "https://example.com/result",
                "snippet": "Result",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/result"],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Search the web",
    )
    worker.token.connect(tokens.append)
    worker.stop()
    worker.run()

    assert "Web results / sources:" not in "".join(tokens)


def test_chat_web_worker_runs_separate_searches_for_multi_part_request(monkeypatch):
    class MultiQueryClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return (
                "32GB GPU graphics cards current models\n"
                "latest Qwen model release\n"
                "64GB DDR4 2x32 current prices Germany"
            )

    seen = []

    def fake_search(query, max_results=6, fetch_pages=True):
        seen.append(query)
        slug = str(len(seen))
        return {
            "provider": "test",
            "query": query,
            "results": [{
                "title": f"Relevant result {slug}",
                "url": f"https://example.com/{slug}",
                "snippet": query,
            }],
        }

    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: [payload["results"][0]["url"]],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: payload["results"][0]["snippet"],
    )

    client = MultiQueryClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        (
            "Keress 32 GB-os videokartyakat.\n"
            "Nezd meg a legfrissebb Qwen modellt.\n"
            "Keress 64 GB DDR4 RAM-ot."
        ),
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert seen == [
        "32GB GPU graphics cards current models",
        "latest Qwen model release",
        "64GB DDR4 2x32 current prices Germany",
    ]
    combined = "".join(tokens)
    assert "Search queries:" in combined
    assert "https://example.com/1" in combined
    assert "https://example.com/2" in combined
    assert "https://example.com/3" in combined


def test_chat_web_worker_appends_markdown_result_links(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["64GB DDR4 2x32 Germany price"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Kingston 64GB DDR4 kit",
                "url": "https://shop.example/kingston-64gb",
                "snippet": "2x32GB DDR4 kit EUR 149",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://shop.example/kingston-64gb"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=10: [{
            "title": "Kingston 64GB DDR4 kit",
            "url": "https://shop.example/kingston-64gb",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "2x32GB DDR4 1000 EUR alatt",
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert (
        "[Kingston 64GB DDR4 kit]"
        "(https://shop.example/kingston-64gb)"
        in combined
    )
    assert "Web results / sources:" in combined
