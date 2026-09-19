import base64
import html
import ipaddress
import os
import socket
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .browser_web_tool import browser_read_pages, browser_search

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BING_WEB_RSS_URL = "https://www.bing.com/search"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"
YAHOO_SEARCH_URL = "https://search.yahoo.com/search"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/150 Safari/537.36"
)


class WebSearchError(RuntimeError):
    pass


def _decode_bing_result_url(url):
    value = str(url or "").strip()
    if not value:
        return ""

    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host in {"bing.com", "www.bing.com"} and parsed.path.startswith("/aclick"):
            return ""
        if host not in {"bing.com", "www.bing.com"} or parsed.path != "/ck/a":
            return value

        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if not encoded:
            return value

        if encoded.startswith("a1"):
            encoded = encoded[2:]

        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode(
            "utf-8",
            errors="strict",
        )
        if decoded.startswith(("http://", "https://")):
            return decoded
    except Exception:
        pass

    return value


def _decode_result_url(url):
    value = str(url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if parsed.path.startswith("/l/") and (
        not parsed.netloc or "duckduckgo.com" in parsed.netloc
    ):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    return value


def _is_public_http_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            return False

        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def _safe_page_text(url, timeout=15.0, max_chars=6000):
    if not _is_public_http_url(url):
        return ""

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        allow_redirects=False,
        stream=True,
    )

    redirects = 0
    while response.is_redirect or response.is_permanent_redirect:
        redirects += 1
        if redirects > 4:
            response.close()
            return ""
        target = response.headers.get("Location", "")
        if not target:
            response.close()
            return ""
        target = requests.compat.urljoin(url, target)
        response.close()
        if not _is_public_http_url(target):
            return ""
        url = target
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )

    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if (
        "text/html" not in content_type
        and "text/plain" not in content_type
        and content_type
    ):
        response.close()
        return ""

    chunks = []
    total = 0
    encoding = response.encoding or "utf-8"
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= 512000:
            break
    response.close()

    raw = b"".join(chunks)
    text = raw.decode(encoding, errors="replace")

    if "html" in content_type or "<html" in text[:500].lower():
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        text = " ".join(soup.stripped_strings)

    text = " ".join(text.split())
    return text[:max_chars]


def _clean_markup(value):
    if not value:
        return ""
    soup = BeautifulSoup(html.unescape(str(value)), "html.parser")
    return " ".join(soup.stripped_strings)


def _parse_bing_rss(xml_text, limit):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = _decode_bing_result_url(
            (item.findtext("link") or "").strip()
        )
        description = _clean_markup(item.findtext("description") or "")
        published = (item.findtext("pubDate") or "").strip()

        if not title or not _is_public_http_url(url):
            continue

        results.append({
            "title": title,
            "url": url,
            "snippet": description,
            "published": published,
            "page_text": "",
        })
        if len(results) >= limit:
            break

    return results


def _brave_api_key():
    return os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()


def brave_search_configured():
    return bool(_brave_api_key())


def _search_brave_api(query, limit, timeout):
    api_key = _brave_api_key()
    if not api_key:
        raise WebSearchError("Brave Search API key is not configured.")

    params = {
        "q": query,
        "count": limit,
        "country": os.environ.get(
            "BRAVE_SEARCH_COUNTRY",
            "DE",
        ).strip().upper() or "DE",
        "safesearch": "moderate",
        "spellcheck": True,
    }
    search_lang = os.environ.get(
        "BRAVE_SEARCH_LANG",
        "",
    ).strip()
    if search_lang:
        params["search_lang"] = search_lang

    response = requests.get(
        BRAVE_WEB_SEARCH_URL,
        params=params,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
            "User-Agent": USER_AGENT,
        },
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = getattr(response, "status_code", "?")
        detail = ""
        code = ""
        try:
            error_payload = response.json()
            error = error_payload.get("error") or {}
            detail = " ".join(str(error.get("detail", "")).split())
            code = " ".join(str(error.get("code", "")).split())
        except Exception:
            detail = " ".join(str(getattr(response, "text", "") or "").split())

        parts = [f"HTTP {status}"]
        if code:
            parts.append(code)
        if detail:
            parts.append(detail[:280])
        raise WebSearchError(
            "Brave Search API " + ": ".join(parts)
        ) from exc

    payload = response.json()

    results = []
    for item in (payload.get("web") or {}).get("results") or []:
        title = " ".join(
            str(item.get("title", "")).split()
        )
        url = str(item.get("url", "")).strip()
        description = " ".join(
            str(item.get("description", "")).split()
        )

        extra_snippets = [
            " ".join(str(value).split())
            for value in item.get("extra_snippets") or []
            if str(value).strip()
        ]
        snippet = " ".join(
            [value for value in [description, *extra_snippets] if value]
        )

        if not title or not _is_public_http_url(url):
            continue

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "published": str(item.get("age", "")).strip(),
            "page_text": "",
        })
        if len(results) >= limit:
            break

    return {
        "provider": "Brave Search API",
        "results": results,
    }


def _search_bing_rss(query, limit, timeout, news=False):
    url = BING_NEWS_RSS_URL if news else BING_WEB_RSS_URL
    params = {
        "q": query,
        "format": "rss",
        "count": limit,
    }
    response = requests.get(
        url,
        params=params,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
        timeout=timeout,
    )
    response.raise_for_status()

    results = _parse_bing_rss(response.text, limit)
    return {
        "provider": "Bing News RSS" if news else "Bing Web RSS",
        "results": results,
    }


def _search_bing_html(query, limit, timeout):
    response = requests.get(
        BING_WEB_RSS_URL,
        params={"q": query, "count": limit},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    for block in soup.select("li.b_algo, div.b_algo"):
        link = block.select_one("h2 a, h3 a")
        if link is None:
            continue

        title = link.get_text(" ", strip=True)
        url = _decode_bing_result_url(
            str(link.get("href", "")).strip()
        )
        snippet_node = block.select_one(
            ".b_caption p, .b_snippet, p"
        )
        snippet = (
            snippet_node.get_text(" ", strip=True)
            if snippet_node is not None
            else ""
        )

        if not title or not _is_public_http_url(url):
            continue

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "published": "",
            "page_text": "",
        })
        if len(results) >= limit:
            break

    return {
        "provider": "Bing HTML",
        "results": results,
    }


def _decode_yahoo_result_url(url):
    value = str(url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if "search.yahoo.com" in host or host.endswith(".yahoo.com"):
        marker = "/RU="
        if marker in parsed.path:
            encoded = parsed.path.split(marker, 1)[1].split("/RK=", 1)[0]
            return unquote(encoded)
    return value


def _search_yahoo_html(query, limit, timeout):
    response = requests.get(
        YAHOO_SEARCH_URL,
        params={"p": query, "n": limit},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    blocks = soup.select(
        "div.dd.algo, div.algo, li div.compTitle"
    )
    if not blocks:
        blocks = soup.select("div#web ol.searchCenterMiddle > li")

    for block in blocks:
        link = block.select_one(
            "h3 a, .compTitle a, a"
        )
        if link is None:
            continue

        title = link.get_text(" ", strip=True)
        url = _decode_yahoo_result_url(link.get("href", ""))
        snippet_node = block.select_one(
            ".compText p, .compText, .fc-falcon, p"
        )
        snippet = (
            snippet_node.get_text(" ", strip=True)
            if snippet_node is not None
            else ""
        )

        if not title or not _is_public_http_url(url):
            continue

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "published": "",
            "page_text": "",
        })
        if len(results) >= limit:
            break

    return {
        "provider": "Yahoo Search HTML",
        "results": results,
    }


def _search_ddg_lite(query, limit, timeout):
    response = requests.post(
        DDG_LITE_URL,
        data={"q": query},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://lite.duckduckgo.com/",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    links = soup.select("a.result-link, a.result-link__a")
    if not links:
        links = [
            node for node in soup.find_all("a")
            if node.get("href") and node.get_text(" ", strip=True)
        ]

    for link in links:
        title = link.get_text(" ", strip=True)
        url = _decode_result_url(link.get("href", ""))
        if not title or not _is_public_http_url(url):
            continue

        parent = link.parent
        snippet = ""
        if parent is not None:
            snippet_node = parent.find_next(
                class_=lambda value: value
                and ("result-snippet" in value or "result__snippet" in value)
            )
            if snippet_node is not None:
                snippet = snippet_node.get_text(" ", strip=True)

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "published": "",
            "page_text": "",
        })
        if len(results) >= limit:
            break

    return {
        "provider": "DuckDuckGo Lite",
        "results": results,
    }


STOP_TERMS = {
    "the", "and", "for", "with", "from", "this", "that", "latest", "news",
    "current", "currently", "recent", "available", "about", "into", "using", "find", "search",
    "keress", "keresd", "meg", "legfrissebb", "fontos", "hirek", "hírek",
    "foglald", "ossze", "össze", "roviden", "röviden", "csak", "konkret",
    "konkrét", "friss", "informaciot", "információt", "irj", "írj",
    "nekem", "kitet", "alatt", "adj", "adni", "kozvetlen", "közvetlen",
    "linket", "linkeket", "linkek", "nemetorszagban", "németországban",
    "germany", "deutschland", "under", "below", "maximum", "max",
}


def _query_terms(query):
    terms = []
    for token in re.findall(r"\w+", str(query).lower(), flags=re.UNICODE):
        if len(token) < 3 or token in STOP_TERMS or token == "site":
            continue
        if token.isdigit() and len(token) < 3:
            continue
        terms.append(token)
    return list(dict.fromkeys(terms))


def _normalized_spec_text(value):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value or "").lower().replace("×", "x"),
    )


def _parse_price_number(value):
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return None

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[-1]
        raw = raw.replace(",", ".") if len(tail) <= 2 else raw.replace(",", "")

    try:
        return float(raw)
    except ValueError:
        return None


def build_search_plan(query):
    clean = " ".join(str(query or "").strip().split())
    text = clean.lower().replace("×", "x")
    folded = text.translate(str.maketrans({
        "á": "a", "é": "e", "í": "i", "ó": "o", "ö": "o",
        "ő": "o", "ú": "u", "ü": "u", "ű": "u",
    }))

    plan = {
        "query": clean,
        "country": "",
        "exact_kit": "",
        "memory_type": "",
        "speed_mhz": None,
        "max_price": None,
        "currency": "",
    }

    kit_match = re.search(
        r"\b\d+\s*x\s*\d+\s*(?:gb|tb)\b",
        text,
        flags=re.IGNORECASE,
    )
    if kit_match:
        plan["exact_kit"] = _normalized_spec_text(kit_match.group(0))

    memory_match = re.search(r"\bddr\s*[345]\b", text, flags=re.IGNORECASE)
    if memory_match:
        plan["memory_type"] = _normalized_spec_text(memory_match.group(0))

    speed_match = re.search(
        r"\b(\d{3,5})\s*(?:mhz|mt/s|mts|mtps)\b",
        text,
        flags=re.IGNORECASE,
    )
    if speed_match:
        plan["speed_mhz"] = int(speed_match.group(1))

    if re.search(r"\b(?:germany|deutschland|nemetorszag)\w*\b", folded):
        plan["country"] = "DE"

    price_patterns = [
        (
            r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<currency>eur|usd)"
            r"\s*(?:alatt|under|below|or less|maximum|max)\b"
        ),
        (
            r"\b(?:under|below|up to|maximum|max|legfeljebb)\s*"
            r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<currency>eur|usd)\b"
        ),
        (
            r"(?P<symbol>[€$])\s*(?P<amount>\d+(?:[.,]\d+)?)"
            r"\s*(?:alatt|under|below|or less|maximum|max)\b"
        ),
        (
            r"\b(?:under|below|up to|maximum|max|legfeljebb)\s*"
            r"(?P<symbol>[€$])\s*(?P<amount>\d+(?:[.,]\d+)?)\b"
        ),
    ]
    price_match = None
    for pattern in price_patterns:
        price_match = re.search(pattern, folded, flags=re.IGNORECASE)
        if price_match:
            break

    if price_match:
        amount = _parse_price_number(price_match.group("amount"))
        currency = price_match.groupdict().get("currency")
        symbol = price_match.groupdict().get("symbol")
        if amount is not None:
            plan["max_price"] = amount
            plan["currency"] = (
                str(currency).upper()
                if currency
                else {"€": "EUR", "$": "USD"}.get(symbol, "")
            )
    else:
        preserved_prices = list(re.finditer(
            r"\b(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<currency>eur|usd)\b",
            folded,
            flags=re.IGNORECASE,
        ))
        if len(preserved_prices) == 1:
            amount = _parse_price_number(preserved_prices[0].group("amount"))
            if amount is not None:
                plan["max_price"] = amount
                plan["currency"] = preserved_prices[0].group("currency").upper()

    return plan


def _format_exact_kit(value):
    normalized = str(value or "").lower()
    match = re.fullmatch(r"(\d+)x(\d+)(gb|tb)", normalized)
    if not match:
        return str(value or "")
    return f"{match.group(1)}x{match.group(2)}{match.group(3).upper()}"


def build_provider_query(plan):
    original = " ".join(str(plan.get("query") or "").split())
    hard_values = [
        plan.get("exact_kit"),
        plan.get("memory_type"),
        plan.get("speed_mhz"),
        plan.get("max_price"),
        plan.get("country"),
    ]
    if not any(value not in {None, ""} for value in hard_values):
        return original

    excluded = {
        _normalized_spec_text(plan.get("exact_kit")),
        _normalized_spec_text(plan.get("memory_type")),
        str(plan.get("speed_mhz") or ""),
        str(int(plan["max_price"])) if isinstance(plan.get("max_price"), float) and plan["max_price"].is_integer() else str(plan.get("max_price") or ""),
        str(plan.get("currency") or "").lower(),
    }
    topic_terms = []
    for term in _query_terms(original):
        normalized = _normalized_spec_text(term)
        if normalized in excluded or term.isdigit():
            continue
        if term not in topic_terms:
            topic_terms.append(term)
        if len(topic_terms) >= 6:
            break

    parts = []
    if plan.get("exact_kit"):
        parts.append(_format_exact_kit(plan["exact_kit"]))
    if plan.get("memory_type"):
        parts.append(str(plan["memory_type"]).upper())
    if plan.get("speed_mhz") is not None:
        parts.append(f"{int(plan['speed_mhz'])} MHz")
    parts.extend(topic_terms)
    if plan.get("country") == "DE":
        parts.append("Germany")
    if plan.get("max_price") is not None and plan.get("currency"):
        amount = float(plan["max_price"])
        display = str(int(amount)) if amount.is_integer() else str(amount)
        parts.append(f"under {display} {plan['currency']}")

    canonical = " ".join(str(value).strip() for value in parts if str(value).strip())
    return canonical[:260] or original


def _hard_query_specs(query):
    plan = build_search_plan(query)
    specs = []
    if plan["exact_kit"]:
        specs.append(("exact", plan["exact_kit"]))
    if plan["memory_type"]:
        specs.append(("exact", plan["memory_type"]))
    if plan["speed_mhz"] is not None:
        specs.append(("speed", str(plan["speed_mhz"])))
    return specs


def _result_evidence_text(item):
    return " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("page_text", "")),
    ]).lower()


def _result_price_values(item, currency):
    evidence = _result_evidence_text(item)
    currency = str(currency or "").upper()
    patterns = []
    if currency == "EUR":
        patterns = [
            r"€\s*(\d+(?:[.,]\d+)?)",
            r"\b(\d+(?:[.,]\d+)?)\s*eur\b",
        ]
    elif currency == "USD":
        patterns = [
            r"\$\s*(\d+(?:[.,]\d+)?)",
            r"\b(\d+(?:[.,]\d+)?)\s*usd\b",
        ]

    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, evidence, flags=re.IGNORECASE):
            value = _parse_price_number(match.group(1))
            if value is not None:
                values.append(value)
    return values


def _validate_result_against_plan(plan, item, require_verified=True):
    evidence = _result_evidence_text(item)
    reasons = []

    requested_kit = str(plan.get("exact_kit") or "")
    if requested_kit:
        found_kits = {
            _normalized_spec_text(match.group(0))
            for match in re.finditer(
                r"\b\d+\s*x\s*\d+\s*(?:gb|tb)\b",
                evidence.replace("×", "x"),
                flags=re.IGNORECASE,
            )
        }
        if requested_kit not in found_kits:
            if found_kits:
                reasons.append("exact_kit_mismatch")
            elif require_verified:
                reasons.append("exact_kit_unverified")

    requested_memory = str(plan.get("memory_type") or "")
    if requested_memory:
        found_memory = {
            _normalized_spec_text(match.group(0))
            for match in re.finditer(
                r"\bddr\s*[345]\b",
                evidence,
                flags=re.IGNORECASE,
            )
        }
        if requested_memory not in found_memory:
            if found_memory:
                reasons.append("memory_type_mismatch")
            elif require_verified:
                reasons.append("memory_type_unverified")

    requested_speed = plan.get("speed_mhz")
    if requested_speed is not None:
        found_speeds = {
            int(match.group(1))
            for match in re.finditer(
                r"\b(\d{3,5})\s*(?:mhz|mt/s|mts|mtps)\b",
                evidence,
                flags=re.IGNORECASE,
            )
        }
        found_speeds.update(
            int(match.group(1))
            for match in re.finditer(
                r"\bddr[345][\s-]+(\d{3,5})\b",
                evidence,
                flags=re.IGNORECASE,
            )
        )
        if int(requested_speed) not in found_speeds:
            if found_speeds:
                reasons.append("speed_mismatch")
            elif require_verified:
                reasons.append("speed_unverified")

    country = str(plan.get("country") or "")
    if country == "DE":
        host = ""
        try:
            host = (urlparse(str(item.get("url", ""))).hostname or "").lower()
        except Exception:
            host = ""
        country_verified = (
            host.endswith(".de")
            or bool(re.search(
                r"\b(?:germany|deutschland|nemetorszag)\w*\b",
                evidence.translate(str.maketrans({
                    "á": "a", "é": "e", "í": "i", "ó": "o", "ö": "o",
                    "ő": "o", "ú": "u", "ü": "u", "ű": "u",
                })),
                flags=re.IGNORECASE,
            ))
        )
        if require_verified and not country_verified:
            reasons.append("country_unverified")

    max_price = plan.get("max_price")
    currency = str(plan.get("currency") or "")
    if max_price is not None and currency:
        prices = _result_price_values(item, currency)
        if prices:
            if min(prices) > float(max_price):
                reasons.append("price_above_max")
        elif require_verified:
            reasons.append("price_unverified")

    return (not reasons), reasons


def _filter_relevant_results(
    query,
    results,
    *,
    plan=None,
    require_verified=True,
):
    terms = _query_terms(query)
    plan = plan or build_search_plan(query)
    if not terms and not any(
        value for key, value in plan.items()
        if key not in {"query", "speed_mhz", "max_price"}
    ) and plan.get("speed_mhz") is None and plan.get("max_price") is None:
        return list(results)

    minimum_matches = 1 if len(terms) <= 2 else 2
    relevant = []

    for item in results:
        valid, _reasons = _validate_result_against_plan(
            plan,
            item,
            require_verified=require_verified,
        )
        if not valid:
            continue

        haystack = " ".join([
            str(item.get("title", "")),
            str(item.get("snippet", "")),
            str(item.get("page_text", "")),
        ]).lower()
        normalized_haystack = _normalized_spec_text(haystack)

        matched = {
            term for term in terms
            if (
                term in haystack
                or _normalized_spec_text(term) in normalized_haystack
            )
        }
        if len(matched) >= minimum_matches:
            relevant.append(item)

    return relevant



_CURRENT_VERSION_MARKERS = (
    "latest",
    "current",
    "newest",
    "legfrissebb",
    "legújabb",
    "legujabb",
    "jelenlegi",
    "aktuell",
    "neueste",
)
_VERSION_TOPIC_MARKERS = (
    "version",
    "release",
    "verzió",
    "verzio",
    "kiadás",
    "kiadas",
)
_ENTITY_SCOPE_QUALIFIERS = {
    "api", "app", "apps", "audio", "cli", "client", "code", "coder",
    "desktop", "docs", "documentation", "driver", "embedding", "examples",
    "extension", "extensions", "gui", "java", "javascript", "js", "math",
    "mobile", "plugin", "plugins", "python", "reranker", "rust", "sdk",
    "server", "studio", "tool", "tools", "ui", "vision", "vl", "web",
    "agent", "agents", "drive",
}

_AUTHORITY_STOPWORDS = {
    "latest", "current", "newest", "version", "release",
    "legfrissebb", "legújabb", "legujabb", "jelenlegi",
    "verzió", "verzio", "kiadás", "kiadas",
    "aktuell", "neueste", "was", "what", "which", "melyik",
    "mi", "az", "a", "the", "is", "ist",
}
_SEMVER_RE = re.compile(
    r"(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+){0,2}"
    r"(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)


def _fold_authority_text(value):
    return " ".join(
        re.sub(
            r"[^a-z0-9._+-]+",
            " ",
            str(value or "").lower().translate(str.maketrans({
                "á": "a", "é": "e", "í": "i", "ó": "o", "ö": "o",
                "ő": "o", "ú": "u", "ü": "u", "ű": "u",
            })),
        ).split()
    )


def is_current_version_query(query):
    normalized = _fold_authority_text(query)
    return (
        any(marker in normalized for marker in _CURRENT_VERSION_MARKERS)
        and any(marker in normalized for marker in _VERSION_TOPIC_MARKERS)
    )


def _authority_identity_terms(query):
    normalized = _fold_authority_text(query)
    terms = [
        token for token in re.findall(r"[a-z0-9][a-z0-9._+-]*", normalized)
        if len(token) >= 3 and token not in _AUTHORITY_STOPWORDS
    ]
    return terms[:6]


def _split_identity_tokens(value):
    folded = _fold_authority_text(value)
    return {
        token for token in re.findall(r"[a-z0-9]+", folded)
        if len(token) >= 2
    }


def _authority_scope_mismatch(query, item):
    """
    Reject a qualified subproduct/tool as the authority for an unqualified family
    query. Example pattern: "Nimbus latest version" must not silently resolve to
    "nimbus-cli" unless the user actually asked for the CLI.

    The rule is generic: qualifiers are product-scope terms, not vendor names.
    """
    if not is_current_version_query(query):
        return False

    query_tokens = _split_identity_tokens(query)
    identity_terms = set(_authority_identity_terms(query))
    if not identity_terms:
        return False

    url = _decode_bing_result_url(str(item.get("url", "")).strip())
    title = str(item.get("title", ""))
    candidate_tokens = _split_identity_tokens(title)

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path_segments = [part for part in parsed.path.split("/") if part]
    except Exception:
        host = ""
        path_segments = []

    if host == "github.com" and len(path_segments) >= 2:
        candidate_tokens.update(_split_identity_tokens(path_segments[1]))

    if not any(term in candidate_tokens for term in identity_terms):
        return False

    candidate_qualifiers = candidate_tokens & _ENTITY_SCOPE_QUALIFIERS
    query_qualifiers = query_tokens & _ENTITY_SCOPE_QUALIFIERS
    return bool(candidate_qualifiers - query_qualifiers)


def _authority_score(query, item):
    if not is_current_version_query(query):
        return 0

    if _authority_scope_mismatch(query, item):
        return -500

    url = _decode_bing_result_url(str(item.get("url", "")).strip())
    title = _fold_authority_text(item.get("title", ""))
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except Exception:
        host = ""
        path = ""

    identity_terms = _authority_identity_terms(query)
    score = 0

    if host == "github.com" and "/releases" in path:
        segments = [part for part in path.split("/") if part]
        repo_identity = " ".join(segments[:2])
        if any(term in repo_identity for term in identity_terms):
            score += 500
        else:
            score += 120

    if any(term in host for term in identity_terms):
        score += 350

    if any(term in title for term in identity_terms):
        score += 80

    if "official" in title or "hivatalos" in title:
        score += 40

    return score


def rank_authoritative_results(query, results):
    indexed = list(enumerate(list(results or [])))
    indexed.sort(
        key=lambda pair: (
            -_authority_score(query, pair[1]),
            pair[0],
        )
    )
    return [item for _index, item in indexed]


def _extract_release_value(item, query=""):
    url = _decode_bing_result_url(str(item.get("url", "")).strip())
    text = "\n".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("page_text", "")),
    ])
    compact = " ".join(text.split())

    try:
        parsed = urlparse(url)
        path = parsed.path
    except Exception:
        path = ""

    tag_match = re.search(
        r"/releases/tag/(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)",
        path,
        flags=re.IGNORECASE,
    )
    if tag_match:
        return tag_match.group(1)

    version_token = (
        r"(?<![A-Za-z0-9])"
        r"(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)"
        r"(?![A-Za-z0-9])"
    )
    patterns = [
        rf"{version_token}\s+Latest\b",
        rf"\bLatest\b\s*(?:stable\s+)?(?:version|release)?\s*[:=-]?\s*"
        rf"{version_token}",
        rf"Release list\s+{version_token}",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    # Product/model families often encode the generation in the name itself
    # (for example "Nimbus3.8"). Prefer that over unrelated decimals such as
    # parameter counts, benchmark scores, or API versions.
    identity_terms = _authority_identity_terms(query)
    for term in identity_terms:
        named_match = re.search(
            rf"\b({re.escape(term)}\s*[-_]?\s*\d+(?:\.\d+){{1,3}})\b",
            compact,
            flags=re.IGNORECASE,
        )
        if named_match:
            return re.sub(r"\s+", "", named_match.group(1))

    # Bare decimals are accepted only when explicit release/version language
    # binds them to the requested fact. This prevents values such as
    # "2.4 trillion parameters" from being misclassified as a version.
    contextual_patterns = [
        r"\b(?:latest|current|newest)\s+(?:stable\s+)?(?:version|release)\s*[:=-]?\s*"
        r"(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)",
        r"\b(?:version|release)\s*[:=-]?\s*"
        r"(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)",
        r"\b(?:verzió|verzio|kiadás|kiadas)\s*[:=-]?\s*"
        r"(v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)",
        r"\b(v\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?)\b",
    ]
    for pattern in contextual_patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def authoritative_current_fact(payload):
    query = str(payload.get("query", "")).strip()
    if not is_current_version_query(query):
        return None

    ranked = rank_authoritative_results(query, payload.get("results") or [])
    for item in ranked:
        score = _authority_score(query, item)
        if score < 300:
            continue

        value = _extract_release_value(item, query=query)
        if not value:
            continue

        url = _decode_bing_result_url(str(item.get("url", "")).strip())
        title = " ".join(str(item.get("title", "")).split()) or url
        return {
            "kind": "latest_release",
            "value": value,
            "url": url,
            "title": title,
            "authority": "first_party",
        }

    return None


def source_urls(payload, limit=10):
    urls = []
    for item in payload.get("results") or []:
        url = _decode_bing_result_url(
            str(item.get("url", "")).strip()
        )
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def source_entries(payload, limit=10):
    entries = []
    seen = set()

    for item in payload.get("results") or []:
        url = _decode_bing_result_url(
            str(item.get("url", "")).strip()
        )
        title = " ".join(
            str(item.get("title", "")).strip().split()
        )
        if not url or url in seen:
            continue

        seen.add(url)
        entries.append({
            "title": title or url,
            "url": url,
        })
        if len(entries) >= limit:
            break

    return entries


def _fetch_top_pages(results, timeout):
    missing = []
    bounded = results[: min(6, len(results))]

    for item in bounded:
        try:
            item["page_text"] = _safe_page_text(
                item["url"],
                timeout=min(timeout, 15.0),
            )
        except Exception:
            item["page_text"] = ""

        if not item.get("page_text"):
            missing.append(item["url"])

    if missing:
        try:
            browser_pages = browser_read_pages(
                missing,
                timeout=min(timeout, 20.0),
            )
        except Exception:
            browser_pages = {}

        for item in bounded:
            if not item.get("page_text"):
                item["page_text"] = browser_pages.get(item["url"], "")


def search_web(query, max_results=6, fetch_pages=True, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise WebSearchError("A web search query is required.")

    search_plan = build_search_plan(clean)
    provider_query = build_provider_query(search_plan)
    limit = max(1, min(int(max_results or 6), 10))
    attempts = []
    if brave_search_configured():
        attempts.append(
            (
                "Brave Search API",
                lambda: _search_brave_api(provider_query, limit, timeout),
            )
        )

    attempts.extend([
        ("Bing Web RSS", lambda: _search_bing_rss(provider_query, limit, timeout, news=False)),
        ("Bing HTML", lambda: _search_bing_html(provider_query, limit, timeout)),
        ("Bing News RSS", lambda: _search_bing_rss(provider_query, limit, timeout, news=True)),
        ("Yahoo Search HTML", lambda: _search_yahoo_html(provider_query, limit, timeout)),
        ("DuckDuckGo Lite", lambda: _search_ddg_lite(provider_query, limit, timeout)),
        ("Edge Browser / Bing", lambda: browser_search(provider_query, limit, timeout)),
    ])
    errors = []

    for name, provider_call in attempts:
        try:
            payload = provider_call()
            results = payload.get("results") or []
            if not results:
                errors.append(f"{name}: no results")
                continue

            results = _filter_relevant_results(
                provider_query,
                results,
                plan=search_plan,
                require_verified=not fetch_pages,
            )
            results = rank_authoritative_results(clean, results)
            if not results:
                errors.append(
                    f"{name}: results failed relevance or hard constraints"
                )
                continue

            if fetch_pages:
                _fetch_top_pages(results, timeout)
                results = _filter_relevant_results(
                    provider_query,
                    results,
                    plan=search_plan,
                    require_verified=False,
                )
                results = rank_authoritative_results(clean, results)
                if not results:
                    errors.append(
                        f"{name}: results contradicted hard constraints after page fetch"
                    )
                    continue

            return {
                "provider": payload.get("provider", name),
                "query": clean,
                "provider_query": provider_query,
                "search_plan": search_plan,
                "retrieved_at": datetime.now().isoformat(timespec="seconds"),
                "results": results,
                "provider_chain_errors": list(errors),
            }
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    raise WebSearchError(
        "Web search failed across all providers. "
        + " | ".join(errors)
    )


def web_search_context_text(payload):
    lines = [
        "WEB SEARCH TOOL DATA",
        f"Provider: {payload.get('provider', '')}",
        f"Retrieved: {payload.get('retrieved_at', '')}",
        f"Query: {payload.get('query', '')}",
    ]
    provider_query = str(payload.get("provider_query", "")).strip()
    if provider_query and provider_query != str(payload.get("query", "")).strip():
        lines.append(f"Provider query: {provider_query}")
    fact = authoritative_current_fact(payload)
    if fact:
        lines.extend([
            "",
            "AUTHORITATIVE CURRENT FACT",
            f"Kind: {fact['kind']}",
            f"Value: {fact['value']}",
            f"Authority: {fact['authority']}",
            f"Source: {fact['title']}",
            f"Source URL: {fact['url']}",
            (
                "Instruction: preserve this exact current value for the requested "
                "latest/current fact; do not replace it with an older secondary-source value."
            ),
        ])

    lines.extend([
        "",
        "SEARCH RESULTS",
    ])

    for index, item in enumerate(payload.get("results") or [], start=1):
        lines.extend([
            f"{index}. {item.get('title', '')}",
            f"URL: {item.get('url', '')}",
            f"Snippet: {item.get('snippet', '')}",
        ])
        if _authority_scope_mismatch(payload.get("query", ""), item):
            lines.append(
                "Scope note: this result is a qualified subproduct/tool not named "
                "in the query; do not use it as the current-version authority."
            )
        if item.get("published"):
            lines.append(f"Published: {item.get('published', '')}")
        page_text = item.get("page_text", "")
        if page_text:
            lines.append(f"Page text: {page_text}")
        lines.append("")

    return "\n".join(lines).strip()
