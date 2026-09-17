from app import workers


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.calls.append((model, messages))
        if not self.responses:
            raise AssertionError("Unexpected extra model call")
        return self.responses.pop(0)


def test_new_hungarian_search_adds_bounded_german_market_query():
    prompt = "Keress nekem teás kannát 100 EUR alatt, és adj közvetlen linkeket."
    client = SequenceClient([
        "teás kanna 100 EUR alatt\nolcsó teáskanna 100 EUR alatt",
        "Teekanne unter 100 EUR kaufen",
    ])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    queries = worker._generate_search_queries()

    assert queries[0] == prompt
    assert len(queries) == 2
    assert "Teekanne" in queries[1]
    assert "100 EUR" in queries[1]
    assert "Deutschland" in queries[1]
    assert len(client.calls) == 2


def test_explicit_country_market_does_not_auto_expand_to_germany():
    prompt = "Keress nekem teás kannát Magyarországon 100 EUR alatt."
    client = SequenceClient([
        "teás kanna Magyarország 100 EUR alatt",
    ])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    queries = worker._generate_search_queries()

    assert queries == ["teás kanna Magyarország 100 EUR alatt"]
    assert len(client.calls) == 1


def test_referential_followup_keeps_existing_context_resolution_path():
    prompt = "Ebből keress olcsóbbat."
    client = SequenceClient([
        "teás kanna olcsóbban",
    ])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress nekem teás kannát 100 EUR alatt."},
            {"role": "assistant", "content": "Korábbi találatok."},
        ],
        prompt,
    )

    queries = worker._generate_search_queries()

    assert queries == ["teás kanna olcsóbban"]
    assert len(client.calls) == 1
