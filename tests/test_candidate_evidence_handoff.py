from app import web_search_tool


def test_search_web_hands_incomplete_candidate_to_evidence_layer(monkeypatch):
    query = (
        "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
        "Nemetorszagban 700 EUR alatt"
    )
    candidate = {
        "title": "G.Skill Ripjaws V 64GB DDR4 3200MHz kit",
        "url": "https://shop.example.de/gskill-64gb",
        "snippet": "2x32GB DDR4 3200 MHz RAM kit Germany",
        "published": "",
        "page_text": "",
    }

    monkeypatch.setattr(
        web_search_tool,
        "brave_search_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_brave_api",
        lambda query, limit, timeout: {
            "provider": "Brave Search API",
            "results": [dict(candidate)],
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_fetch_top_pages",
        lambda results, timeout: results[0].update({
            "page_text": "Product page without a machine-readable price."
        }),
    )

    payload = web_search_tool.search_web(query, fetch_pages=True)

    assert payload["provider"] == "Brave Search API"
    assert payload["results"][0]["url"] == candidate["url"]
    assert payload["search_plan"]["max_price"] == 700.0
    assert "price" not in payload["results"][0]


def test_candidate_filter_still_rejects_explicit_wrong_kit():
    query = "2x32GB DDR4 3200 MHz RAM Germany 700 EUR"
    results = [{
        "title": "G.Skill Ripjaws V 32GB DDR4 3200MHz",
        "url": "https://shop.example.de/wrong-kit",
        "snippet": "2x16GB DDR4 3200 MHz 199 EUR Germany",
        "page_text": "",
    }]

    filtered = web_search_tool._filter_relevant_results(
        query,
        results,
        plan=web_search_tool.build_search_plan(query),
        require_verified=False,
    )

    assert filtered == []
