from decimal import Decimal

import pytest

from app.multi_asset_market_data import (
    MultiAssetMarketDataError,
    format_multi_asset_quote_answer,
    get_multi_asset_quote,
    infer_multi_asset_quote_request,
    is_multi_asset_quote_request,
)


@pytest.mark.parametrize(
    ("prompt", "symbol", "asset_class"),
    [
        ("Mennyi most a Tesla részvény ára?", "TSLA", "stock"),
        ("What is the current AAPL stock price?", "AAPL", "stock"),
        ("Mi az EUR/USD árfolyama most?", "EURUSD=X", "forex"),
        ("Wie hoch ist der DAX Kurs aktuell?", "^GDAXI", "index"),
        ("What is the Nasdaq market price?", "^IXIC", "index"),
    ],
)
def test_multi_asset_quote_intent_recognizes_stock_forex_and_index(
    prompt,
    symbol,
    asset_class,
):
    request = infer_multi_asset_quote_request(prompt)

    assert request is not None
    assert request["symbol"] == symbol
    assert request["asset_class"] == asset_class
    assert is_multi_asset_quote_request(prompt)


def test_multi_asset_quote_intent_does_not_capture_stable_explanations_or_crypto():
    assert infer_multi_asset_quote_request("Mi az a Tesla részvény?") is None
    assert infer_multi_asset_quote_request("What is an exchange rate?") is None
    assert infer_multi_asset_quote_request("Mennyi most a bitcoin árfolyama?") is None


def test_generic_uppercase_ticker_is_supported_when_price_intent_is_explicit():
    request = infer_multi_asset_quote_request("What is the current AMD stock price?")

    assert request == {
        "symbol": "AMD",
        "asset_name": "AMD",
        "asset_class": "stock",
    }


def test_multi_asset_quote_reads_chart_meta_and_calculates_change():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "chart": {
                    "error": None,
                    "result": [
                        {
                            "meta": {
                                "currency": "USD",
                                "symbol": "TSLA",
                                "exchangeName": "NMS",
                                "instrumentType": "EQUITY",
                                "regularMarketPrice": 250.0,
                                "previousClose": 245.0,
                                "marketState": "REGULAR",
                            }
                        }
                    ],
                }
            }

    calls = []

    def requester(url, params, timeout):
        calls.append((url, params, timeout))
        return Response()

    extension = {
        "timeout": 7,
        "config": {
            "api_base_url": "https://query1.finance.yahoo.com/v8/finance/chart",
        },
    }

    quote = get_multi_asset_quote(
        extension,
        "Mennyi most a Tesla részvény ára?",
        requester=requester,
    )

    assert quote["symbol"] == "TSLA"
    assert quote["asset_class"] == "stock"
    assert quote["price"] == "250.0"
    assert quote["currency"] == "USD"
    assert quote["exchange"] == "NMS"
    assert quote["market_state"] == "REGULAR"
    assert Decimal(quote["change_percent"]) == Decimal("2.04")
    assert calls == [
        (
            "https://query1.finance.yahoo.com/v8/finance/chart/TSLA",
            {"interval": "1m", "range": "1d"},
            7.0,
        )
    ]


def test_multi_asset_quote_rejects_invalid_https_base():
    extension = {
        "config": {
            "api_base_url": "http://example.com/chart",
        }
    }

    with pytest.raises(MultiAssetMarketDataError, match="must use HTTPS"):
        get_multi_asset_quote(
            extension,
            "Mennyi most a Tesla részvény ára?",
            requester=lambda *_args, **_kwargs: None,
        )


def test_multi_asset_answer_is_concise_hungarian_and_grounded():
    answer = format_multi_asset_quote_answer(
        {
            "provider": "Yahoo Finance chart endpoint",
            "retrieved_at": "2026-09-19T18:00:00+00:00",
            "symbol": "TSLA",
            "asset_name": "Tesla",
            "asset_class": "stock",
            "price": "250.15",
            "currency": "USD",
            "change_percent": "1.25",
            "exchange": "NMS",
            "market_state": "REGULAR",
            "source_url": "https://finance.yahoo.com/quote/TSLA/",
        },
        "Mennyi most a Tesla részvény ára?",
    )

    assert "Tesla (TSLA)" in answer
    assert "250.15 USD" in answer
    assert "+1.25%" in answer
    assert "Yahoo Finance chart endpoint" in answer
    assert "2026-09-19T18:00:00+00:00" in answer


def test_multi_asset_quote_retries_query2_after_query1_failure():
    calls = []

    class BadResponse:
        def raise_for_status(self):
            raise RuntimeError("query1 unavailable")

        def json(self):
            return {}

    class GoodResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "chart": {
                    "error": None,
                    "result": [{
                        "meta": {
                            "currency": "USD",
                            "regularMarketPrice": 364.27,
                            "previousClose": 366.20,
                            "exchangeName": "NMS",
                            "marketState": "REGULAR",
                        }
                    }],
                }
            }

    def requester(url, params, timeout, headers=None):
        calls.append((url, headers))
        return BadResponse() if "query1.finance.yahoo.com" in url else GoodResponse()

    extension = {
        "config": {
            "api_base_url": "https://query1.finance.yahoo.com/v8/finance/chart",
        }
    }

    quote = get_multi_asset_quote(
        extension,
        "Mennyi most a Tesla részvény ára?",
        requester=requester,
    )

    assert quote["price"] == "364.27"
    assert len(calls) == 2
    assert "query1.finance.yahoo.com" in calls[0][0]
    assert "query2.finance.yahoo.com" in calls[1][0]
    assert calls[0][1]["Accept"].startswith("application/json")
