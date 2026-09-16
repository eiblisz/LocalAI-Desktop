from app import browser_web_tool


def test_browser_parser_reads_bing_results(monkeypatch):
    html = """
    <html><body>
      <li class="b_algo">
        <h2><a href="https://example.com/item">Example item</a></h2>
        <div class="b_caption"><p>Example snippet.</p></div>
      </li>
    </body></html>
    """
    monkeypatch.setattr(
        browser_web_tool,
        "_is_public_http_url",
        lambda url: True,
    )

    results = browser_web_tool._parse_bing_results(html, 5)

    assert len(results) == 1
    assert results[0]["title"] == "Example item"
    assert results[0]["url"] == "https://example.com/item"
    assert results[0]["snippet"] == "Example snippet."


def test_browser_tool_rejects_local_addresses():
    assert browser_web_tool._is_public_http_url(
        "http://127.0.0.1/private"
    ) is False
    assert browser_web_tool._is_public_http_url(
        "http://localhost/private"
    ) is False


def test_browser_block_page_detection():
    assert browser_web_tool._page_is_blocked(
        "Please verify you are human"
    ) is True
    assert browser_web_tool._page_is_blocked(
        "Normal public article text"
    ) is False


def test_read_only_route_blocks_post():
    class FakeRoute:
        def __init__(self):
            self.action = ""

        def abort(self):
            self.action = "abort"

        def continue_(self):
            self.action = "continue"

    class FakeRequest:
        method = "POST"
        resource_type = "xhr"
        url = "https://example.com/api"

    route = FakeRoute()
    browser_web_tool._route_read_only(route, FakeRequest())

    assert route.action == "abort"
