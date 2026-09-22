from app import workers
from app import web_search_tool


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def test_rejected_model_answer_is_replaced_by_verified_host_fallback(monkeypatch):
    plan = web_search_tool.build_search_plan(QUERY)
    result = {
        "title": "Crucial 64GB Kit DDR4-3200",
        "url": "https://shop.example.de/crucial-64gb",
        "snippet": "2x32GB DDR4 3200 MHz, 606.90 EUR, Deutschland",
        "page_text": "Crucial memory kit 2 x 32 GB DDR4 3200 MHz",
    }

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: [QUERY],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "search_plan": plan,
            "results": [result],
        },
    )

    class Client:
        def chat_once(self, model, messages, timeout=600.0):
            return QUERY

        def chat_stream(self, model, messages, on_token, should_stop):
            on_token(
                "Crucial 2x32GB DDR4 3200 MHz 608 EUR"
            )

    tokens = []
    worker = workers.ChatWebWorker(
        Client(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        QUERY,
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert "608 EUR" not in combined
    assert "606.90 EUR" in combined
    assert "https://shop.example.de/crucial-64gb" in combined
    assert "Az ellenorzott forrasok alapjan:" in combined
    assert (
        worker.diagnostic_metadata["verification_status"]
        == "Evidence verification: PASS (host-verified fallback used)"
    )
