from app import ebay_tool


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_ebay_search_parses_public_result_cards(monkeypatch):
    html = """
    <html><body>
      <li class="s-item">
        <div class="s-item__title">Shop on eBay</div>
      </li>
      <li class="s-item">
        <div class="s-item__title">Kingston Fury 64GB DDR4</div>
        <a class="s-item__link" href="https://www.ebay.de/itm/123">Offer</a>
        <span class="s-item__price">EUR 119,00</span>
        <span class="s-item__shipping">EUR 5,49 Versand</span>
      </li>
    </body></html>
    """

    monkeypatch.setattr(
        ebay_tool.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(html),
    )

    result = ebay_tool.search_ebay("Kingston Fury 64GB", max_results=5)
    text = ebay_tool.ebay_context_text(result)

    assert result["provider"] == "eBay.de public search"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Kingston Fury 64GB DDR4"
    assert "EUR 119,00" in text
    assert "https://www.ebay.de/itm/123" in text


def test_ebay_search_falls_back_to_web_search(monkeypatch):
    monkeypatch.setattr(
        ebay_tool.requests,
        "get",
        lambda *args, **kwargs: FakeResponse("<html><body>No cards</body></html>"),
    )
    monkeypatch.setattr(
        ebay_tool,
        "search_web",
        lambda query, max_results=8, fetch_pages=False, timeout=20.0: {
            "provider": "Bing Web RSS",
            "results": [{
                "title": "Kingston Fury 64GB DDR4 EUR 120,00",
                "url": "https://www.ebay.de/itm/456",
                "snippet": "Used kit EUR 120,00",
            }],
        },
    )

    result = ebay_tool.search_ebay("Kingston Fury 64GB", max_results=5)

    assert result["provider"] == "eBay.de via Bing Web RSS"
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://www.ebay.de/itm/456"
    assert result["results"][0]["price"] == "EUR 120,00"
