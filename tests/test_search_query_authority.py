from app import workers


class QueryClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        return self.response


def test_hard_constrained_single_topic_ignores_model_query_drift():
    prompt = (
        "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
        "Németországban 700 EUR alatt, és adj közvetlen linkeket is."
    )
    client = QueryClient(
        "DDR4 3200MHz 64GB RAM kit Hungary\n"
        "G.Skill Ripjaws V 32GB DDR4 3200MHz\n"
        "Corsair Vengeance LPX 32GB DDR4 3200MHz"
    )
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    queries = worker._generate_search_queries()

    assert queries == [prompt]
    assert "Hungary" not in queries[0]
    assert "2x32GB" in queries[0]
    assert "DDR4" in queries[0]
    assert "3200 MHz" in queries[0]
    assert "Németországban" in queries[0]
    assert "700 EUR" in queries[0]


def test_multi_topic_request_keeps_independent_generated_queries():
    client = QueryClient(
        "latest Qwen model release\n"
        "64GB DDR4 2x32 current prices Germany"
    )
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        (
            "Nézd meg a legfrissebb Qwen modellt. "
            "Keress 2x32GB DDR4 RAM-ot 200 EUR alatt."
        ),
    )

    assert worker._generate_search_queries() == [
        "latest Qwen model release",
        "64GB DDR4 2x32 current prices Germany",
    ]
