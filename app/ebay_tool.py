from datetime import datetime
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

EBAY_SEARCH_URL = "https://www.ebay.de/sch/i.html"


class EbaySearchError(RuntimeError):
    pass


def search_ebay(query, max_results=8, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise EbaySearchError("An eBay search query is required.")

    params = {"_nkw": clean}
    response = requests.get(
        EBAY_SEARCH_URL,
        params=params,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            )
        },
        timeout=timeout,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for item in soup.select("li.s-item"):
        title_node = item.select_one(".s-item__title")
        link_node = item.select_one("a.s-item__link")
        price_node = item.select_one(".s-item__price")
        shipping_node = item.select_one(".s-item__shipping, .s-item__logisticsCost")

        title = title_node.get_text(" ", strip=True) if title_node else ""
        link = link_node.get("href", "") if link_node else ""
        price = price_node.get_text(" ", strip=True) if price_node else ""
        shipping = shipping_node.get_text(" ", strip=True) if shipping_node else ""

        if not title or title.lower() == "shop on ebay" or not link:
            continue

        results.append({
            "title": title,
            "price": price,
            "shipping": shipping,
            "url": link,
        })
        if len(results) >= max(1, min(int(max_results), 20)):
            break

    if not results:
        raise EbaySearchError(
            "eBay returned no parseable results. The page layout or access policy may have changed."
        )

    return {
        "provider": "eBay.de public search",
        "query": clean,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "search_url": EBAY_SEARCH_URL + "?" + urlencode(params),
        "results": results,
    }


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
            f"price={item.get('price', '')} | "
            f"shipping={item.get('shipping', '')} | "
            f"url={item.get('url', '')}"
        )
    return "\n".join(lines)
