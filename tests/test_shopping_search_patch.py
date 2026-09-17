from app import web_search_tool
from app.shopping_search_patch import _is_generic_shopping_url


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def test_memory_kit_provider_query_adds_total_capacity_and_purchase_intent():
    plan = web_search_tool.build_search_plan(QUERY)
    query = web_search_tool.build_provider_query(plan)

    assert "2x32GB" in query
    assert "64GB" in query
    assert "DDR4" in query
    assert "3200 MHz" in query
    assert "RAM" in query
    assert "kit" in query.lower()
    assert "kaufen" in query.lower()
    assert "Germany" in query
    assert "Deutschland" in query
    assert "under 700 EUR" in query


def test_generic_shopping_urls_are_detected_without_rejecting_product_pages():
    assert _is_generic_shopping_url(
        "https://www.ebay.de/sch/i.html?_nkw=2x32gb+ddr4"
    )
    assert _is_generic_shopping_url(
        "https://www.amazon.de/s?k=2x32gb+ddr4"
    )
    assert _is_generic_shopping_url(
        "https://shop.example.de/search?query=2x32gb"
    )

    assert not _is_generic_shopping_url(
        "https://www.ebay.de/itm/123456789"
    )
    assert not _is_generic_shopping_url(
        "https://shop.example.de/products/kingston-fury-64gb"
    )


def test_memory_kit_filter_prefers_product_urls_over_generic_search_urls():
    plan = web_search_tool.build_search_plan(QUERY)
    results = [
        {
            "title": "64GB 2x32GB DDR4 3200 MHz RAM",
            "url": "https://www.ebay.de/sch/i.html?_nkw=2x32gb+ddr4",
            "snippet": "2x32GB DDR4 3200 MHz Germany 180 EUR",
            "page_text": "",
        },
        {
            "title": "Kingston Fury Beast 64GB 2x32GB DDR4 3200 MHz",
            "url": "https://shop.example.de/products/kingston-fury-64gb",
            "snippet": "2x32GB DDR4 3200 MHz Germany 189 EUR",
            "page_text": "",
        },
    ]

    filtered = web_search_tool._filter_relevant_results(
        web_search_tool.build_provider_query(plan),
        results,
        plan=plan,
        require_verified=True,
    )

    assert [item["url"] for item in filtered] == [
        "https://shop.example.de/products/kingston-fury-64gb"
    ]


def test_non_shopping_provider_query_is_unchanged():
    plan = web_search_tool.build_search_plan("OpenAI latest news")
    assert web_search_tool.build_provider_query(plan) == "OpenAI latest news"
