import pytest

from app import workers
from app.web_research_pipeline import BILINGUAL_QUERY_SCHEMA


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0, response_format=None):
        self.calls.append((model, messages, response_format))
        if not self.responses:
            raise AssertionError("Unexpected extra model call")
        return self.responses.pop(0)


def test_new_hungarian_search_adds_normalized_hungarian_and_german_queries():
    prompt = "Keress nekem teas kannat 100 EUR alatt."
    client = SequenceClient([
        '{"hu_query":"teaskanna 100 EUR alatt",'
        '"de_query":"Teekanne unter 100 EUR kaufen Deutschland"}',
    ])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    queries = worker._generate_search_queries()

    assert queries == [
        "teaskanna 100 EUR alatt",
        "Teekanne unter 100 EUR kaufen Deutschland",
    ]
    assert len(client.calls) == 1
    assert "SEARCH AUTHORITY:" in client.calls[0][1][-1]["content"]
    assert client.calls[0][2] == BILINGUAL_QUERY_SCHEMA


def test_invalid_bilingual_plan_fails_closed_without_legacy_query_fallback():
    prompt = "Keress nekem teas kannat 100 EUR alatt."
    client = SequenceClient(["teas kannat 100 EUR alatt"])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    with pytest.raises(
        RuntimeError,
        match="Bilingual shopping query planning failed closed",
    ):
        worker._generate_search_queries()

    assert len(client.calls) == 1
    assert client.calls[0][2] == BILINGUAL_QUERY_SCHEMA


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


def test_non_shopping_hungarian_research_does_not_auto_expand():
    prompt = "Keress ra a legfrissebb Qwen hirekre"
    client = SequenceClient([
        "Qwen local AI latest news",
    ])
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    assert worker._generate_search_queries() == ["Qwen local AI latest news"]
    assert len(client.calls) == 1
