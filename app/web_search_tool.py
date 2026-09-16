import ipaddress
import socket
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://html.duckduckgo.com/html/"
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
            return ""
        target = response.headers.get("Location", "")
        if not target:
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
    for chunk in response.iter_content(chunk_size=16384):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= 512000:
            break
    response.close()

    raw = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    text = raw.decode(encoding, errors="replace")

    if "html" in content_type or "<html" in text[:500].lower():
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        text = " ".join(soup.stripped_strings)

    text = " ".join(text.split())
    return text[:max_chars]


def search_web(query, max_results=6, fetch_pages=True, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise WebSearchError("A web search query is required.")

    limit = max(1, min(int(max_results or 6), 10))
    response = requests.get(
        SEARCH_URL,
        params={"q": clean},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if link is None:
            continue

        title = link.get_text(" ", strip=True)
        url = _decode_result_url(link.get("href", ""))
        snippet_node = result.select_one(".result__snippet")
        snippet = (
            snippet_node.get_text(" ", strip=True)
            if snippet_node is not None
            else ""
        )

        if not title or not _is_public_http_url(url):
            continue

        item = {
            "title": title,
            "url": url,
            "snippet": snippet,
            "page_text": "",
        }
        results.append(item)
        if len(results) >= limit:
            break

    if not results:
        raise WebSearchError(
            "Web search returned no usable public results. "
            "The search provider may be unavailable or its page format may have changed."
        )

    if fetch_pages:
        for item in results[: min(3, len(results))]:
            try:
                item["page_text"] = _safe_page_text(
                    item["url"],
                    timeout=min(timeout, 15.0),
                )
            except Exception:
                item["page_text"] = ""

    return {
        "provider": "DuckDuckGo HTML",
        "query": clean,
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }


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
        page_text = item.get("page_text", "")
        if page_text:
            lines.append(f"Page text: {page_text}")
        lines.append("")

    return "\n".join(lines).strip()
