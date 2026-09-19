import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlparse

import requests

from .language_policy import detect_user_language


DEFAULT_API_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

ASSET_ALIASES = {
    "tesla": ("TSLA", "Tesla", "stock"),
    "tsla": ("TSLA", "Tesla", "stock"),
    "apple": ("AAPL", "Apple", "stock"),
    "aapl": ("AAPL", "Apple", "stock"),
    "microsoft": ("MSFT", "Microsoft", "stock"),
    "msft": ("MSFT", "Microsoft", "stock"),
    "nvidia": ("NVDA", "NVIDIA", "stock"),
    "nvda": ("NVDA", "NVIDIA", "stock"),
    "amazon": ("AMZN", "Amazon", "stock"),
    "amzn": ("AMZN", "Amazon", "stock"),
    "meta": ("META", "Meta", "stock"),
    "alphabet": ("GOOGL", "Alphabet", "stock"),
    "google": ("GOOGL", "Alphabet", "stock"),
    "googl": ("GOOGL", "Alphabet", "stock"),
    "s&p 500": ("^GSPC", "S&P 500", "index"),
    "sp500": ("^GSPC", "S&P 500", "index"),
    "s&p500": ("^GSPC", "S&P 500", "index"),
    "nasdaq": ("^IXIC", "Nasdaq Composite", "index"),
    "dow jones": ("^DJI", "Dow Jones Industrial Average", "index"),
    "dow": ("^DJI", "Dow Jones Industrial Average", "index"),
    "dax": ("^GDAXI", "DAX", "index"),
    "eur/usd": ("EURUSD=X", "EUR/USD", "forex"),
    "eurusd": ("EURUSD=X", "EUR/USD", "forex"),
    "gbp/usd": ("GBPUSD=X", "GBP/USD", "forex"),
    "gbpusd": ("GBPUSD=X", "GBP/USD", "forex"),
    "usd/jpy": ("JPY=X", "USD/JPY", "forex"),
    "usdjpy": ("JPY=X", "USD/JPY", "forex"),
    "usd/chf": ("CHF=X", "USD/CHF", "forex"),
    "usdchf": ("CHF=X", "USD/CHF", "forex"),
}

PRICE_MARKERS = (
    "árfolyam",
    "arfolyam",
    "ára",
    "ara",
    "mennyi most",
    "aktuális ár",
    "aktualis ar",
    "piaci ár",
    "piaci ar",
    "részvény ára",
    "reszveny ara",
    "price",
    "market price",
    "stock price",
    "share price",
    "quote",
    "exchange rate",
    "kurs",
    "preis",
    "aktienkurs",
    "wechselkurs",
)


class MultiAssetMarketDataError(RuntimeError):
    pass


def _fold(value):
    return " ".join(str(value or "").casefold().split())


def infer_multi_asset_quote_request(text):
    original = str(text or "")
    normalized = _fold(original)
    if not normalized:
        return None

    asset = None
    for alias in sorted(ASSET_ALIASES, key=len, reverse=True):
        if re.search(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
            normalized,
            flags=re.IGNORECASE,
        ):
            asset = ASSET_ALIASES[alias]
            break

    has_price_intent = any(marker in normalized for marker in PRICE_MARKERS)

    if asset is None and has_price_intent:
        symbols = re.findall(
            r"(?<![A-Za-z0-9])([A-Z]{2,5})(?![A-Za-z0-9])",
            original,
        )
        ignored = {"USD", "EUR", "GBP", "JPY", "CHF", "BTC", "ETH", "SOL", "XRP"}
        for symbol in symbols:
            if symbol not in ignored:
                asset = (symbol, symbol, "stock")
                break

    if asset is None:
        return None

    explicit_pair = "/" in normalized or "=x" in normalized
    if not has_price_intent and not explicit_pair:
        return None

    return {
        "symbol": asset[0],
        "asset_name": asset[1],
        "asset_class": asset[2],
    }


def is_multi_asset_quote_request(text):
    return infer_multi_asset_quote_request(text) is not None


def _api_base_from_extension(extension):
    extension = dict(extension or {})
    config = dict(extension.get("config") or {})
    value = str(config.get("api_base_url") or DEFAULT_API_BASE).strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MultiAssetMarketDataError(
            "Multi-Asset Market Data API base URL must use HTTPS."
        )
    return value.rstrip("/")


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _change_percent(last, previous):
    last_value = _decimal(last)
    previous_value = _decimal(previous)
    if last_value is None or previous_value in {None, Decimal("0")}:
        return None
    return ((last_value - previous_value) / previous_value) * Decimal("100")


def _chart_payload(response):
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MultiAssetMarketDataError(f"Market quote request failed: {exc}") from exc

    try:
        payload = response.json()
    except Exception as exc:
        raise MultiAssetMarketDataError("Market quote returned invalid JSON") from exc

    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise MultiAssetMarketDataError("Market quote returned an unexpected payload")
    if chart.get("error"):
        raise MultiAssetMarketDataError(f"Market quote error: {chart.get('error')}")

    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise MultiAssetMarketDataError("Market quote returned no result")
    result = results[0]
    if not isinstance(result, dict):
        raise MultiAssetMarketDataError("Market quote result is invalid")
    return result


def get_multi_asset_quote(extension, prompt, requester=requests.get):
    request = infer_multi_asset_quote_request(prompt)
    if not request:
        raise MultiAssetMarketDataError(
            "The request is not a supported stock, forex or index quote query."
        )

    base_url = _api_base_from_extension(extension)
    timeout = float((extension or {}).get("timeout", 10.0) or 10.0)
    symbol = request["symbol"]
    url = f"{base_url}/{quote(symbol, safe='')}"
    params = {"interval": "1m", "range": "1d"}

    try:
        response = requester(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise MultiAssetMarketDataError(f"Market quote request failed: {exc}") from exc

    result = _chart_payload(response)
    meta = result.get("meta") or {}

    price = meta.get("regularMarketPrice")
    if price is None:
        price = meta.get("chartPreviousClose")
    if price is None:
        raise MultiAssetMarketDataError("Market quote did not contain a price.")

    previous = meta.get("previousClose")
    if previous is None:
        previous = meta.get("chartPreviousClose")

    change = _change_percent(price, previous)
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "provider": "Yahoo Finance chart endpoint",
        "retrieved_at": retrieved_at,
        "symbol": symbol,
        "asset_name": request["asset_name"],
        "asset_class": request["asset_class"],
        "price": str(price),
        "previous_close": "" if previous is None else str(previous),
        "change_percent": (
            str(change.quantize(Decimal("0.01"))) if change is not None else ""
        ),
        "currency": str(meta.get("currency") or "").strip(),
        "exchange": str(meta.get("exchangeName") or meta.get("fullExchangeName") or "").strip(),
        "market_state": str(meta.get("marketState") or "").strip(),
        "source_url": f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/",
    }


def _format_number(value, max_decimals=6):
    number = _decimal(value)
    if number is None:
        return str(value or "")
    return f"{number:.{max_decimals}f}".rstrip("0").rstrip(".")


def format_multi_asset_quote_answer(quote_data, prompt):
    data = dict(quote_data or {})
    language = detect_user_language(prompt)
    name = data.get("asset_name") or data.get("symbol") or "Market"
    symbol = data.get("symbol") or ""
    price = _format_number(data.get("price"))
    currency = data.get("currency") or ""
    change = str(data.get("change_percent") or "").strip()
    exchange = data.get("exchange") or ""
    state = data.get("market_state") or ""
    provider = data.get("provider") or "market data provider"
    source_url = data.get("source_url") or ""
    retrieved = data.get("retrieved_at") or ""

    source = f"[{provider}]({source_url})" if source_url else provider
    label = f"{name} ({symbol})" if symbol and symbol != name else name
    price_text = f"{price} {currency}".strip()

    details = []
    if change:
        details.append(f"{Decimal(change):+.2f}%")
    if exchange:
        details.append(exchange)
    if state:
        details.append(state)
    details_text = " · ".join(details)

    if language == "hu":
        first = f"A {label} aktuális piaci ára: **{price_text}**."
        second = f"Változás / piac: {details_text}." if details_text else ""
        third = f"Forrás: {source}; lekérve: {retrieved}."
    elif language == "de":
        first = f"Der aktuelle Marktpreis von {label}: **{price_text}**."
        second = f"Änderung / Markt: {details_text}." if details_text else ""
        third = f"Quelle: {source}; abgerufen: {retrieved}."
    else:
        first = f"The current market price of {label} is **{price_text}**."
        second = f"Change / market: {details_text}." if details_text else ""
        third = f"Source: {source}; retrieved: {retrieved}."

    return " ".join(part for part in (first, second, third) if part)


def run_multi_asset_market_request(extension, prompt, requester=requests.get):
    quote_data = get_multi_asset_quote(extension, prompt, requester=requester)
    return format_multi_asset_quote_answer(quote_data, prompt)
