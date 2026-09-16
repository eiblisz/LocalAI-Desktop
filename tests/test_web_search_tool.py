from app import web_search_tool


class SearchResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_web_search_parses_public_results(monkeypatch):
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="https://example.com/article">Example result</a>
        <div class="result__snippet">Fresh information about the topic.</div>
      </div>
    </body></html>
    """

    monkeypatch.setattr(
        web_search_tool.requests,
        "get",
        lambda *args, **kwargs: SearchResponse(html),
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

    assert payload["provider"] == "DuckDuckGo HTML"
    assert payload["results"][0]["title"] == "Example result"
    assert payload["results"][0]["url"] == "https://example.com/article"
    assert "Fresh information about the topic." in text


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
