import html
import ipaddress
import socket
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .browser_web_tool import browser_read_pages, browser_search

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
        url = (item.findtext("link") or "").strip()
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
        url = str(link.get("href", "")).strip()
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


def _filter_relevant_results(query, results):
    terms = _query_terms(query)
    if not terms:
        return list(results)

    minimum_matches = 1 if len(terms) <= 2 else 2
    relevant = []

    for item in results:
        haystack = " ".join([
            str(item.get("title", "")),
            str(item.get("snippet", "")),
            str(item.get("url", "")),
        ]).lower()

        matched = {
            term for term in terms
            if term in haystack
        }
        if len(matched) >= minimum_matches:
            relevant.append(item)

    return relevant


def source_urls(payload, limit=10):
    urls = []
    for item in payload.get("results") or []:
        url = str(item.get("url", "")).strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _fetch_top_pages(results, timeout):
    missing = []

    for item in results[: min(3, len(results))]:
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

        for item in results[: min(3, len(results))]:
            if not item.get("page_text"):
                item["page_text"] = browser_pages.get(item["url"], "")


def search_web(query, max_results=6, fetch_pages=True, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise WebSearchError("A web search query is required.")

    limit = max(1, min(int(max_results or 6), 10))
    attempts = [
        ("Bing Web RSS", lambda: _search_bing_rss(clean, limit, timeout, news=False)),
        ("Bing HTML", lambda: _search_bing_html(clean, limit, timeout)),
        ("Bing News RSS", lambda: _search_bing_rss(clean, limit, timeout, news=True)),
        ("Yahoo Search HTML", lambda: _search_yahoo_html(clean, limit, timeout)),
        ("DuckDuckGo Lite", lambda: _search_ddg_lite(clean, limit, timeout)),
        ("Edge Browser / Bing", lambda: browser_search(clean, limit, timeout)),
    ]
    errors = []

    for name, provider_call in attempts:
        try:
            payload = provider_call()
            results = payload.get("results") or []
            if not results:
                errors.append(f"{name}: no results")
                continue

            results = _filter_relevant_results(clean, results)
            if not results:
                errors.append(f"{name}: results were not relevant to the query")
                continue

            if fetch_pages:
                _fetch_top_pages(results, timeout)

            return {
                "provider": payload.get("provider", name),
                "query": clean,
                "retrieved_at": datetime.now().isoformat(timespec="seconds"),
                "results": results,
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
        "",
        "SEARCH RESULTS",
    ]

    for index, item in enumerate(payload.get("results") or [], start=1):
        lines.extend([
            f"{index}. {item.get('title', '')}",
            f"URL: {item.get('url', '')}",
            f"Snippet: {item.get('snippet', '')}",
        ])
        if item.get("published"):
            lines.append(f"Published: {item.get('published', '')}")
        page_text = item.get("page_text", "")
        if page_text:
            lines.append(f"Page text: {page_text}")
        lines.append("")

    return "\n".join(lines).strip()
