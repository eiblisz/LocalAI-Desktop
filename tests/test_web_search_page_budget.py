from app import web_search_tool


def test_search_web_accepts_bounded_integer_page_fetch_budget(monkeypatch):
    results = [
        {
            "title": f"Example source {index}",
            "url": f"https://example.com/{index}",
            "snippet": "Example topic evidence",
        }
        for index in range(5)
    ]
    fetch_calls = []

    monkeypatch.setattr(web_search_tool, "brave_context_mode", lambda: "legacy")
    monkeypatch.setattr(web_search_tool, "brave_search_configured", lambda: True)
    monkeypatch.setattr(
        web_search_tool,
        "_search_brave_api",
        lambda query, limit, timeout: {
            "provider": "Brave Search API",
            "results": list(results),
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_filter_relevant_results",
        lambda query, items, plan=None, require_verified=True: list(items),
    )
    monkeypatch.setattr(
        web_search_tool,
        "rank_authoritative_results",
        lambda query, items: list(items),
    )

    def capture_fetch(items, timeout, limit=6):
        fetch_calls.append((len(items), timeout, limit))
        for item in items[:limit]:
            item["page_text"] = "Fetched evidence"

    monkeypatch.setattr(web_search_tool, "_fetch_top_pages", capture_fetch)

    payload = web_search_tool.search_web(
        "Example topic",
        max_results=8,
        fetch_pages=2,
        timeout=20.0,
    )

    assert fetch_calls == [(5, 8.0, 2)]
    assert payload["timing"]["page_fetch_count"] == 2
    assert payload["timing"]["usable_sources"] == 5


def test_boolean_fetch_pages_keeps_legacy_six_page_budget(monkeypatch):
    results = [
        {
            "title": f"Example source {index}",
            "url": f"https://example.com/{index}",
            "snippet": "Example topic evidence",
        }
        for index in range(8)
    ]
    fetch_calls = []

    monkeypatch.setattr(web_search_tool, "brave_context_mode", lambda: "legacy")
    monkeypatch.setattr(web_search_tool, "brave_search_configured", lambda: True)
    monkeypatch.setattr(
        web_search_tool,
        "_search_brave_api",
        lambda query, limit, timeout: {
            "provider": "Brave Search API",
            "results": list(results),
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_filter_relevant_results",
        lambda query, items, plan=None, require_verified=True: list(items),
    )
    monkeypatch.setattr(
        web_search_tool,
        "rank_authoritative_results",
        lambda query, items: list(items),
    )

    def capture_fetch(items, timeout, limit=6):
        fetch_calls.append((len(items), timeout, limit))
        for item in items[:limit]:
            item["page_text"] = "Fetched evidence"

    monkeypatch.setattr(web_search_tool, "_fetch_top_pages", capture_fetch)

    payload = web_search_tool.search_web(
        "Example topic",
        max_results=8,
        fetch_pages=True,
        timeout=20.0,
    )

    assert fetch_calls == [(8, 15.0, 6)]
    assert payload["timing"]["page_fetch_count"] == 6
