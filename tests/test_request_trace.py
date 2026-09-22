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
