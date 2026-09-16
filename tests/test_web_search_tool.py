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
    text = web_search_tool.web_search_context_text(payload)

    assert payload["provider"] == "Bing Web RSS"
    assert payload["results"][0]["title"] == "Example result"
    assert payload["results"][0]["url"] == "https://example.com/article"
    assert "Fresh information about the topic." in text


def test_web_search_falls_back_to_bing_news_when_web_empty(monkeypatch):
    empty = "<?xml version='1.0'?><rss><channel></channel></rss>"
    news = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Fresh AI news</title>
        <link>https://example.com/news</link>
        <description>Current update.</description>
      </item>
    </channel></rss>
    """
    calls = []

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if "news/search" in url:
            return SearchResponse(news)
        return SearchResponse(empty)

    monkeypatch.setattr(web_search_tool.requests, "get", fake_get)
    monkeypatch.setattr(
        web_search_tool,
        "_is_public_http_url",
        lambda url: True,
    )

    payload = web_search_tool.search_web(
        "AI news",
        max_results=5,
        fetch_pages=False,
    )

    assert payload["provider"] == "Bing News RSS"
    assert payload["results"][0]["title"] == "Fresh AI news"
    assert any("news/search" in url for url in calls)


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
