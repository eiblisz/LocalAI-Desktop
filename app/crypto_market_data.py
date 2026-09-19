import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests

from .language_policy import detect_user_language


DEFAULT_API_BASE = "https://api.exchange.coinbase.com"
SUPPORTED_QUOTES = {"USD", "EUR", "GBP", "USDC"}

ASSET_ALIASES = {
    "bitcoin": ("BTC", "Bitcoin"),
    "btc": ("BTC", "Bitcoin"),
    "xbt": ("BTC", "Bitcoin"),
    "ethereum": ("ETH", "Ethereum"),
    "ether": ("ETH", "Ethereum"),
    "eth": ("ETH", "Ethereum"),
    "solana": ("SOL", "Solana"),
    "sol": ("SOL", "Solana"),
    "ripple": ("XRP", "XRP"),
    "xrp": ("XRP", "XRP"),
    "cardano": ("ADA", "Cardano"),
    "ada": ("ADA", "Cardano"),
    "dogecoin": ("DOGE", "Dogecoin"),
    "doge": ("DOGE", "Dogecoin"),
    "litecoin": ("LTC", "Litecoin"),
    "ltc": ("LTC", "Litecoin"),
    "chainlink": ("LINK", "Chainlink"),
    "link": ("LINK", "Chainlink"),
    "avalanche": ("AVAX", "Avalanche"),
    "avax": ("AVAX", "Avalanche"),
    "polkadot": ("DOT", "Polkadot"),
    "dot": ("DOT", "Polkadot"),
}

PRICE_MARKERS = (
    "árfolyam",
    "arfolyam",
    "árfolyama",
    "arfolyama",
    "ára",
    "ara",
    "mennyi most",
    "aktuális ár",
    "aktualis ar",
    "piaci ár",
    "piaci ar",
    "spot ár",
    "spot ar",
    "price",
    "market price",
    "spot price",
    "kurs",
    "preis",
    "wert",
)


class CryptoMarketDataError(RuntimeError):
    pass


def _fold(value):
    return " ".join(str(value or "").casefold().split())


def infer_crypto_quote_request(text, default_quote="USD"):
    normalized = _fold(text)
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

    if asset is None:
        return None

    has_price_intent = any(marker in normalized for marker in PRICE_MARKERS)
    has_pair = any(
        token in normalized.upper()
        for token in (
            f"{asset[0]}/USD",
            f"{asset[0]}-USD",
            f"{asset[0]}/EUR",
            f"{asset[0]}-EUR",
            f"{asset[0]}/GBP",
            f"{asset[0]}-GBP",
        )
    )
    if not has_price_intent and not has_pair:
        return None

    quote = str(default_quote or "USD").strip().upper() or "USD"
    for candidate in ("USD", "EUR", "GBP", "USDC"):
        if candidate.casefold() in normalized or f"/{candidate.lower()}" in normalized:
            quote = candidate
            break

    if quote not in SUPPORTED_QUOTES:
        return None

    return {
        "symbol": asset[0],
        "asset_name": asset[1],
        "quote_currency": quote,
    }


def is_crypto_quote_request(text):
    return infer_crypto_quote_request(text) is not None


def _json_response(response, label):
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CryptoMarketDataError(f"{label} request failed: {exc}") from exc

    try:
        body = response.json()
    except Exception as exc:
        raise CryptoMarketDataError(f"{label} returned invalid JSON") from exc

    if not isinstance(body, dict):
        raise CryptoMarketDataError(f"{label} returned an unexpected payload")
    if body.get("message"):
        raise CryptoMarketDataError(f"{label}: {body.get('message')}")
    return body


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _change_percent(last, open_value):
    last_value = _decimal(last)
    open_decimal = _decimal(open_value)
    if last_value is None or open_decimal in {None, Decimal("0")}:
        return None
    return ((last_value - open_decimal) / open_decimal) * Decimal("100")


def _api_base_from_extension(extension):
    extension = dict(extension or {})
    config = dict(extension.get("config") or {})
    value = str(config.get("api_base_url") or DEFAULT_API_BASE).strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CryptoMarketDataError("Crypto Market Data API base URL must use HTTPS.")
    return value.rstrip("/")


def get_crypto_quote(extension, prompt, requester=requests.get):
    extension = dict(extension or {})
    request = infer_crypto_quote_request(
        prompt,
        default_quote=(extension.get("config") or {}).get("default_quote", "USD"),
    )
    if not request:
        raise CryptoMarketDataError("The request is not a supported crypto quote query.")

    base_url = _api_base_from_extension(extension)
    product = f"{request['symbol']}-{request['quote_currency']}"
    timeout = float(extension.get("timeout", 10.0) or 10.0)

    ticker_url = f"{base_url}/products/{product}/ticker"
    try:
        ticker_response = requester(ticker_url, timeout=timeout)
    except requests.RequestException as exc:
        raise CryptoMarketDataError(f"Market quote request failed: {exc}") from exc
    ticker = _json_response(ticker_response, "Market quote")

    price = str(ticker.get("price") or ticker.get("last") or "").strip()
    if not price:
        raise CryptoMarketDataError("Market quote did not contain a price.")

    stats = {}
    stats_url = f"{base_url}/products/{product}/stats"
    try:
        stats_response = requester(stats_url, timeout=timeout)
        stats = _json_response(stats_response, "24h stats")
    except Exception:
        stats = {}

    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    change = _change_percent(price, stats.get("open"))

    return {
        "provider": "Coinbase Exchange public market data",
        "retrieved_at": retrieved_at,
        "symbol": request["symbol"],
        "asset_name": request["asset_name"],
        "quote_currency": request["quote_currency"],
        "product": product,
        "price": price,
        "bid": str(ticker.get("bid") or "").strip(),
        "ask": str(ticker.get("ask") or "").strip(),
        "volume_24h": str(stats.get("volume") or ticker.get("volume") or "").strip(),
        "high_24h": str(stats.get("high") or "").strip(),
        "low_24h": str(stats.get("low") or "").strip(),
        "open_24h": str(stats.get("open") or "").strip(),
        "change_24h_percent": str(change.quantize(Decimal("0.01"))) if change is not None else "",
        "source_url": ticker_url,
    }


def _format_number(value, max_decimals=8):
    number = _decimal(value)
    if number is None:
        return str(value or "")
    text = f"{number:.{max_decimals}f}".rstrip("0").rstrip(".")
    return text


def format_crypto_quote_answer(quote, prompt):
    quote = dict(quote or {})
    language = detect_user_language(prompt)
    asset_name = quote.get("asset_name") or quote.get("symbol") or "Crypto"
    symbol = quote.get("symbol") or ""
    currency = quote.get("quote_currency") or "USD"
    price = _format_number(quote.get("price"), max_decimals=8)
    change = str(quote.get("change_24h_percent") or "").strip()
    high = _format_number(quote.get("high_24h"), max_decimals=8)
    low = _format_number(quote.get("low_24h"), max_decimals=8)
    provider = quote.get("provider") or "market data provider"
    source_url = quote.get("source_url") or ""
    retrieved = quote.get("retrieved_at") or ""

    source = f"[{provider}]({source_url})" if source_url else provider
    asset_label = f"{asset_name} ({symbol})" if symbol else asset_name

    if language == "hu":
        first = f"A {asset_label} aktuális ára: **{price} {currency}**."
        details = []
        if change:
            details.append(f"24h: **{Decimal(change):+.2f}%**")
        if low and high:
            details.append(f"min/max: {low} / {high} {currency}")
        second = (" ".join(details) + ".") if details else ""
        third = f"Forrás: {source}; lekérve: {retrieved}."
    elif language == "de":
        first = f"Der aktuelle Preis von {asset_label}: **{price} {currency}**."
        details = []
        if change:
            details.append(f"24h: **{Decimal(change):+.2f}%**")
        if low and high:
            details.append(f"Tief/Hoch: {low} / {high} {currency}")
        second = (" ".join(details) + ".") if details else ""
        third = f"Quelle: {source}; abgerufen: {retrieved}."
    else:
        first = f"The current price of {asset_label} is **{price} {currency}**."
        details = []
        if change:
            details.append(f"24h: **{Decimal(change):+.2f}%**")
        if low and high:
            details.append(f"low/high: {low} / {high} {currency}")
        second = (" ".join(details) + ".") if details else ""
        third = f"Source: {source}; retrieved: {retrieved}."

    return " ".join(part for part in (first, second, third) if part)


def run_crypto_market_request(extension, prompt, requester=requests.get):
    quote = get_crypto_quote(extension, prompt, requester=requester)
    return format_crypto_quote_answer(quote, prompt)
