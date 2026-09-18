from app import workers


class DummyClient:
    pass


class DummyStore:
    pass


def test_memory_write_worker_persists_explicit_request(monkeypatch):
    calls = []

    def fake_remember(client, model, user_text, store, *, source_chat_id=None):
        calls.append({
            "client": client,
            "model": model,
            "user_text": user_text,
            "store": store,
            "source_chat_id": source_chat_id,
        })
        return [{"id": "one"}, {"id": "two"}]

    monkeypatch.setattr(workers, "remember_explicit_request", fake_remember)

    client = DummyClient()
    store = DummyStore()
    worker = workers.MemoryWriteWorker(
        client,
        "qwen-test",
        "Jegyezd meg ezt.",
        store,
        "chat-42",
    )
    finished = []
    failed = []
    worker.finished.connect(lambda: finished.append(True))
    worker.failed.connect(failed.append)

    worker.run()

    assert worker.saved_count == 2
    assert finished == [True]
    assert failed == []
    assert calls == [{
        "client": client,
        "model": "qwen-test",
        "user_text": "Jegyezd meg ezt.",
        "store": store,
        "source_chat_id": "chat-42",
    }]


def test_memory_write_worker_reports_failure(monkeypatch):
    def fake_remember(*args, **kwargs):
        raise ValueError("memory rejected")

    monkeypatch.setattr(workers, "remember_explicit_request", fake_remember)

    worker = workers.MemoryWriteWorker(
        DummyClient(),
        "qwen-test",
        "Jegyezd meg ezt.",
        DummyStore(),
        "chat-42",
    )
    finished = []
    failed = []
    worker.finished.connect(lambda: finished.append(True))
    worker.failed.connect(failed.append)

    worker.run()

    assert finished == []
    assert failed == ["memory rejected"]
    assert worker.saved_count == 0


def test_memory_write_worker_stop_is_safe_noop():
    worker = workers.MemoryWriteWorker(
        DummyClient(),
        "qwen-test",
        "Jegyezd meg ezt.",
        DummyStore(),
        "chat-42",
    )

    assert worker.stop() is None
