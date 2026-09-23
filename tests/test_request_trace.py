from app.request_trace import RequestTrace


def test_request_trace_never_stores_secret_metadata():
    trace = RequestTrace("desktop")
    trace.add_metadata(
        api_key="super-secret-key",
        authorization="Bearer secret",
        provider="Brave LLM Context",
    )

    snapshot = trace.snapshot()
    serialized = repr(snapshot)

    assert "super-secret-key" not in serialized
    assert "Bearer secret" not in serialized
    assert snapshot["metadata"]["provider"] == "Brave LLM Context"


def test_request_trace_accumulates_phase_durations():
    trace = RequestTrace("discord")
    trace.mark_duration("page_fetch", 10.5)
    trace.add_duration("page_fetch", 4.5)

    snapshot = trace.snapshot()

    assert snapshot["transport"] == "discord"
    assert snapshot["phases_ms"]["page_fetch"] == 15.0


def test_child_trace_links_to_batch_and_contains_build_identity(monkeypatch):
    monkeypatch.setattr("app.build_identity.BUILD_SHA", "a" * 40)
    monkeypatch.setattr("app.build_identity.EXPECTED_MAIN_SHA", "b" * 40)
    root = RequestTrace("desktop")
    child = RequestTrace(
        "desktop",
        batch_trace_id=root.request_id,
        child_index=1,
        batch_size=3,
    )

    snapshot = child.snapshot()

    assert snapshot["batch_trace_id"] == root.request_id
    assert snapshot["child_trace_id"] == child.request_id
    assert snapshot["metadata"]["child_index"] == 1
    assert snapshot["metadata"]["batch_size"] == 3
    assert snapshot["build_sha"] == "a" * 40
    assert snapshot["expected_main_sha"] == "b" * 40
