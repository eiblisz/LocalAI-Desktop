import re
from datetime import datetime
from urllib.parse import urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from .web_search_tool import search_web

EBAY_SEARCH_URL = "https://www.ebay.de/sch/i.html"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/150 Safari/537.36"
)


class EbaySearchError(RuntimeError):
    pass


def _price_from_text(text):
    value = str(text or "")
    patterns = [
        r"(?:EUR|€)\s*[\d.]+(?:,\d{1,2})?",
        r"[\d.]+(?:,\d{1,2})?\s*(?:EUR|€)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return ""


def _direct_ebay_search(clean, limit, timeout):
    params = {"_nkw": clean}
    response = requests.get(
        EBAY_SEARCH_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for item in soup.select("li.s-item"):
        title_node = item.select_one(".s-item__title")
        link_node = item.select_one("a.s-item__link")
        price_node = item.select_one(".s-item__price")
        shipping_node = item.select_one(
            ".s-item__shipping, .s-item__logisticsCost"
        )

        title = title_node.get_text(" ", strip=True) if title_node else ""
        link = link_node.get("href", "") if link_node else ""
        price = price_node.get_text(" ", strip=True) if price_node else ""
        shipping = (
            shipping_node.get_text(" ", strip=True)
            if shipping_node else ""
        )

        if not title or title.lower() == "shop on ebay" or not link:
            continue

        results.append({
            "title": title,
            "price": price,
            "shipping": shipping,
            "snippet": "",
            "url": link,
        })
        if len(results) >= limit:
            break

    return results, EBAY_SEARCH_URL + "?" + urlencode(params)


def _is_ebay_item_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return (
            host == "ebay.de"
            or host.endswith(".ebay.de")
        ) and "/itm/" in parsed.path
    except Exception:
        return False


def _web_fallback(clean, limit, timeout):
    payload = search_web(
        f"site:ebay.de/itm {clean}",
        max_results=min(limit, 10),
        fetch_pages=False,
        timeout=timeout,
    )

    results = []
    for item in payload.get("results") or []:
        url = item.get("url", "")
        if not _is_ebay_item_url(url):
            continue

        snippet = item.get("snippet", "")
        results.append({
            "title": item.get("title", ""),
            "price": _price_from_text(
                item.get("title", "") + " " + snippet
            ),
            "shipping": "",
            "snippet": snippet,
            "url": url,
        })
        if len(results) >= limit:
            break

    return results, payload


def search_ebay(query, max_results=8, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise EbaySearchError("An eBay search query is required.")

    limit = max(1, min(int(max_results or 8), 20))
    errors = []

    try:
        results, search_url = _direct_ebay_search(
            clean,
            limit,
            timeout,
        )
        if results:
            return {
                "provider": "eBay.de public search",
                "query": clean,
                "retrieved_at": datetime.now().isoformat(timespec="seconds"),
                "search_url": search_url,
                "results": results,
            }
        errors.append("direct eBay: no parseable results")
    except Exception as exc:
        errors.append(f"direct eBay: {exc}")

    try:
        results, web_payload = _web_fallback(
            clean,
            limit,
            timeout,
        )
        if results:
            return {
                "provider": (
                    "eBay.de via "
                    + web_payload.get("provider", "web search")
                ),
                "query": clean,
                "retrieved_at": datetime.now().isoformat(timespec="seconds"),
                "search_url": EBAY_SEARCH_URL + "?" + urlencode({"_nkw": clean}),
                "results": results,
            }
        errors.append("web fallback: no eBay item results")
    except Exception as exc:
        errors.append(f"web fallback: {exc}")

    raise EbaySearchError(
        "eBay search failed. " + " | ".join(errors)
    )


def ebay_context_text(payload):
    lines = [
        "EBAY SEARCH TOOL DATA",
        f"Provider: {payload.get('provider', '')}",
        f"Retrieved: {payload.get('retrieved_at', '')}",
        f"Query: {payload.get('query', '')}",
        f"Search URL: {payload.get('search_url', '')}",
        "",
        "RESULTS",
    ]

    for index, item in enumerate(payload.get("results") or [], start=1):
        lines.append(
            f"{index}. {item.get('title', '')} | "
            f"price={item.get('price', '') or 'not provided'} | "
            f"shipping={item.get('shipping', '') or 'not provided'} | "
            f"url={item.get('url', '')}"
        )
        snippet = item.get("snippet", "")
        if snippet:
            lines.append(f"   snippet={snippet}")
    return "\n".join(lines)
