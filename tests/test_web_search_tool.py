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
                "title": "HTML result",
                "url": "https://example.com/html",
                "snippet": "HTML snippet",
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
    assert payload["results"][0]["title"] == "HTML result"


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
                "title": "Yahoo result",
                "url": "https://example.com/yahoo",
                "snippet": "Yahoo snippet",
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
    assert payload["results"][0]["title"] == "Yahoo result"


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
