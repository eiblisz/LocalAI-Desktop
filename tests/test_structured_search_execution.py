from app import web_search_tool


def test_provider_query_preserves_constraints_and_removes_request_boilerplate():
    original = (
        "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
        "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
    )

    plan = web_search_tool.build_search_plan(original)
    query = web_search_tool.build_provider_query(plan)

    assert "2x32GB" in query
    assert "DDR4" in query
    assert "3200 MHz" in query
    assert "ram" in query.lower()
    assert "Germany" in query
    assert "under 700 EUR" in query
    assert "Hungary" not in query
    assert "Keress nekem" not in query
    assert "Nemetorszagban" not in query
    assert "kozvetlen linkeket" not in query


def test_page_evidence_fetch_covers_all_six_bounded_candidates(monkeypatch):
    seen = []

    def fake_page_text(url, timeout=15.0, max_chars=6000):
        seen.append(url)
        return f"Evidence for {url}"

    monkeypatch.setattr(web_search_tool, "_safe_page_text", fake_page_text)
    monkeypatch.setattr(
        web_search_tool,
        "browser_read_pages",
        lambda urls, timeout=20.0: {},
    )

    results = [
        {
            "title": f"Result {index}",
            "url": f"https://example.com/{index}",
            "snippet": "",
            "page_text": "",
        }
        for index in range(6)
    ]

    web_search_tool._fetch_top_pages(results, 20.0)

    assert seen == [f"https://example.com/{index}" for index in range(6)]
    assert all(item["page_text"] for item in results)


def test_search_web_uses_provider_query_but_keeps_original_constraint_authority(monkeypatch):
    original = (
        "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
        "Nemetorszagban 700 EUR alatt"
    )
    seen = {}

    monkeypatch.setattr(web_search_tool, "brave_search_configured", lambda: True)

    def fake_brave(query, limit, timeout):
        seen["query"] = query
        return {
            "provider": "Brave Search API",
            "results": [{
                "title": "64GB kit 2x32GB DDR4-3200",
                "url": "https://shop.example.de/ram",
                "snippet": "2x32GB DDR4 3200 MHz Germany 199 EUR",
                "published": "",
                "page_text": "",
            }],
        }

    monkeypatch.setattr(web_search_tool, "_search_brave_api", fake_brave)
    monkeypatch.setattr(
        web_search_tool,
        "_fetch_top_pages",
        lambda results, timeout: None,
    )

    payload = web_search_tool.search_web(original, fetch_pages=True)

    assert payload["query"] == original
    assert payload["provider_query"] == seen["query"]
    assert "2x32GB" in seen["query"]
    assert "Germany" in seen["query"]
    assert payload["search_plan"]["exact_kit"] == "2x32gb"
    assert payload["search_plan"]["country"] == "DE"
    assert payload["results"][0]["url"] == "https://shop.example.de/ram"
