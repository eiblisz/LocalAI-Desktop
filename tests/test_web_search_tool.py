from app import web_search_tool


class SearchResponse:
    def __init__(self, text):
        self.text = text
        self.encoding = "utf-8"
        self.is_redirect = False
        self.is_permanent_redirect = False
        self.headers = {"Content-Type": "application/rss+xml"}

    def raise_for_status(self):
        return None

    def close(self):
        return None


def test_web_search_uses_bing_rss_primary(monkeypatch):
    rss = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Example result</title>
        <link>https://example.com/article</link>
        <description>Fresh information about the topic.</description>
      </item>
    </channel></rss>
    """

    monkeypatch.setattr(
        web_search_tool.requests,
        "get",
        lambda *args, **kwargs: SearchResponse(rss),
    )
    monkeypatch.setattr(
        web_search_tool,
        "_is_public_http_url",
        lambda url: True,
    )

    payload = web_search_tool.search_web(
        "example topic",
        max_results=5,
        fetch_pages=False,
    )

    assert payload["provider"] == "Bing Web RSS"
    assert payload["results"][0]["title"] == "Example result"


def test_web_search_falls_back_to_bing_html(monkeypatch):
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_rss",
        lambda *args, **kwargs: {
            "provider": "Bing Web RSS",
            "results": [],
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_html",
        lambda *args, **kwargs: {
            "provider": "Bing HTML",
            "results": [{
                "title": "Example HTML result",
                "url": "https://example.com/html",
                "snippet": "Example HTML snippet",
                "published": "",
                "page_text": "",
            }],
        },
    )

    payload = web_search_tool.search_web(
        "example",
        fetch_pages=False,
    )

    assert payload["provider"] == "Bing HTML"
    assert payload["results"][0]["title"] == "Example HTML result"


def test_web_search_falls_back_to_yahoo_after_bing_paths(monkeypatch):
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_rss",
        lambda *args, **kwargs: {
            "provider": "Bing",
            "results": [],
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_html",
        lambda *args, **kwargs: {
            "provider": "Bing HTML",
            "results": [],
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_yahoo_html",
        lambda *args, **kwargs: {
            "provider": "Yahoo Search HTML",
            "results": [{
                "title": "Example Yahoo result",
                "url": "https://example.com/yahoo",
                "snippet": "Example Yahoo snippet",
                "published": "",
                "page_text": "",
            }],
        },
    )

    payload = web_search_tool.search_web(
        "example",
        fetch_pages=False,
    )

    assert payload["provider"] == "Yahoo Search HTML"
    assert payload["results"][0]["title"] == "Example Yahoo result"


def test_web_search_rejects_loopback_urls():
    assert web_search_tool._is_public_http_url("http://127.0.0.1/private") is False
    assert web_search_tool._is_public_http_url("http://localhost/private") is False


def test_duckduckgo_redirect_url_is_decoded():
    url = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fexample.com%2Fnews%3Fa%3D1"
    )
    assert (
        web_search_tool._decode_result_url(url)
        == "https://example.com/news?a=1"
    )


def test_relative_duckduckgo_redirect_url_is_decoded():
    url = "/l/?uddg=https%3A%2F%2Fexample.com%2Ffresh"
    assert (
        web_search_tool._decode_result_url(url)
        == "https://example.com/fresh"
    )


def test_yahoo_redirect_url_is_decoded():
    url = (
        "https://r.search.yahoo.com/_ylt=abc/"
        "RU=https%3A%2F%2Fexample.com%2Fstory/RK=2/RS=xyz"
    )
    assert (
        web_search_tool._decode_yahoo_result_url(url)
        == "https://example.com/story"
    )


def test_web_search_uses_edge_browser_as_final_fallback(monkeypatch):
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_rss",
        lambda *args, **kwargs: {"provider": "Bing", "results": []},
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_bing_html",
        lambda *args, **kwargs: {"provider": "Bing HTML", "results": []},
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_yahoo_html",
        lambda *args, **kwargs: {"provider": "Yahoo", "results": []},
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_ddg_lite",
        lambda *args, **kwargs: {"provider": "DDG", "results": []},
    )
    monkeypatch.setattr(
        web_search_tool,
        "browser_search",
        lambda query, max_results=6, timeout=20.0: {
            "provider": "Edge Browser / Bing",
            "results": [{
                "title": "Browser result",
                "url": "https://example.com/browser",
                "snippet": "Rendered result",
                "published": "",
                "page_text": "",
            }],
        },
    )

    payload = web_search_tool.search_web(
        "browser fallback",
        fetch_pages=False,
    )

    assert payload["provider"] == "Edge Browser / Bing"
    assert payload["results"][0]["title"] == "Browser result"


def test_page_read_falls_back_to_edge_browser(monkeypatch):
    monkeypatch.setattr(
        web_search_tool,
        "_safe_page_text",
        lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(
        web_search_tool,
        "browser_read_pages",
        lambda urls, timeout=20.0: {
            urls[0]: "Rendered browser page text"
        },
    )

    results = [{
        "title": "Result",
        "url": "https://example.com/page",
        "snippet": "",
        "published": "",
        "page_text": "",
    }]

    web_search_tool._fetch_top_pages(results, 20.0)

    assert results[0]["page_text"] == "Rendered browser page text"


def test_relevance_filter_drops_unrelated_results():
    results = [
        {
            "title": "Amazon Music Unlimited review",
            "url": "https://example.com/music",
            "snippet": "Streaming music and Alexa integration",
        },
        {
            "title": "Qwen local AI model update",
            "url": "https://example.com/qwen",
            "snippet": "New Ollama-compatible local model release",
        },
    ]

    filtered = web_search_tool._filter_relevant_results(
        "local AI models Ollama Qwen",
        results,
    )

    assert [item["title"] for item in filtered] == [
        "Qwen local AI model update"
    ]


def test_source_urls_are_deduplicated():
    payload = {
        "results": [
            {"url": "https://example.com/a"},
            {"url": "https://example.com/a"},
            {"url": "https://example.com/b"},
        ]
    }
    assert web_search_tool.source_urls(payload) == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_relevance_filter_rejects_single_weak_match_for_specific_query():
    results = [
        {
            "title": "My Hero Ultra Rumble discussion",
            "url": "https://reddit.com/r/MyHeroUltraRumble/example",
            "snippet": "A game discussion with unrelated content.",
        },
        {
            "title": "32GB GPU graphics card workstation options",
            "url": "https://example.com/gpu",
            "snippet": "Professional graphics cards with 32GB memory.",
        },
    ]

    filtered = web_search_tool._filter_relevant_results(
        "32GB GPU graphics card",
        results,
    )

    assert [item["url"] for item in filtered] == [
        "https://example.com/gpu"
    ]


def test_bing_redirect_url_is_decoded_to_target():
    url = (
        "https://www.bing.com/ck/a?"
        "u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wcm9kdWN0"
    )
    assert (
        web_search_tool._decode_bing_result_url(url)
        == "https://example.com/product"
    )


def test_source_entries_use_direct_urls_and_titles():
    payload = {
        "results": [
            {
                "title": "Example product",
                "url": (
                    "https://www.bing.com/ck/a?"
                    "u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wcm9kdWN0"
                ),
            }
        ]
    }

    assert web_search_tool.source_entries(payload) == [
        {
            "title": "Example product",
            "url": "https://example.com/product",
        }
    ]


def test_relevance_filter_does_not_match_query_terms_only_from_redirect_url():
    results = [
        {
            "title": "General news",
            "url": "https://www.bing.com/ck/a?u=graphics-card-32gb",
            "snippet": "Unrelated general article",
        }
    ]

    assert (
        web_search_tool._filter_relevant_results(
            "32GB graphics card",
            results,
        )
        == []
    )
