from app.crypto_market_data import (
    format_crypto_quote_answer,
    get_crypto_quote,
    infer_crypto_quote_request,
    is_crypto_quote_request,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_crypto_quote_intent_detects_live_price_but_not_definition():
    assert is_crypto_quote_request("Mennyi most a bitcoin árfolyama?")
    assert is_crypto_quote_request("What is the ETH/USD price?")
    assert is_crypto_quote_request("Wie hoch ist der Bitcoin Kurs aktuell?")
    assert not is_crypto_quote_request("Mi az a Bitcoin?")
    assert not is_crypto_quote_request("Magyarázd el a blokkláncot.")


def test_crypto_quote_request_extracts_asset_and_quote_currency():
    request = infer_crypto_quote_request("Mennyi most az Ethereum ára EUR-ban?")

    assert request["symbol"] == "ETH"
    assert request["asset_name"] == "Ethereum"
    assert request["quote_currency"] == "EUR"


def test_get_crypto_quote_uses_structured_public_market_endpoints():
    calls = []

    def requester(url, timeout=10):
        calls.append((url, timeout))
        if url.endswith("/ticker"):
            return FakeResponse({
                "price": "81632.88",
                "bid": "81630.10",
                "ask": "81635.20",
                "volume": "1234.5",
            })
        if url.endswith("/stats"):
            return FakeResponse({
                "open": "80728.00",
                "high": "82100.00",
                "low": "80000.00",
                "volume": "1250.0",
            })
        raise AssertionError(url)

    extension = {
        "enabled": True,
        "timeout": 7,
        "capabilities": ["crypto_quote", "crypto_ticker", "crypto_24h"],
        "config": {
            "api_base_url": "https://api.exchange.coinbase.com",
            "default_quote": "USD",
        },
    }

    quote = get_crypto_quote(
        extension,
        "Mennyi most a bitcoin árfolyama?",
        requester=requester,
    )

    assert quote["provider"] == "Coinbase Exchange public market data"
    assert quote["symbol"] == "BTC"
    assert quote["quote_currency"] == "USD"
    assert quote["price"] == "81632.88"
    assert quote["high_24h"] == "82100.00"
    assert quote["low_24h"] == "80000.00"
    assert quote["change_24h_percent"]
    assert calls[0][0].endswith("/products/BTC-USD/ticker")
    assert calls[1][0].endswith("/products/BTC-USD/stats")


def test_market_quote_answer_is_concise_and_source_grounded():
    answer = format_crypto_quote_answer(
        {
            "provider": "Coinbase Exchange public market data",
            "retrieved_at": "2026-09-19T15:00:00+00:00",
            "symbol": "BTC",
            "asset_name": "Bitcoin",
            "quote_currency": "USD",
            "price": "81632.88",
            "change_24h_percent": "1.12",
            "high_24h": "82100.00",
            "low_24h": "80000.00",
            "source_url": "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
        },
        "Mennyi most a bitcoin árfolyama?",
    )

    assert "81632.88 USD" in answer
    assert "24h" in answer
    assert "Coinbase Exchange public market data" in answer
    assert "https://api.exchange.coinbase.com/products/BTC-USD/ticker" in answer
    assert len(answer) < 500


def test_unknown_or_non_crypto_price_does_not_claim_market_extension():
    assert infer_crypto_quote_request("Mi a Tesla részvény ára most?") is None
    assert infer_crypto_quote_request("Mennyi most az EUR/USD árfolyam?") is None
