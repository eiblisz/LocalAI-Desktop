import ipaddress
import os
import socket
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


class BrowserToolError(RuntimeError):
    pass


EDGE_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
]


def _is_public_http_url(url):
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False

        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"}:
            return False

        addresses = socket.getaddrinfo(
            host,
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


def _launch_edge(playwright):
    errors = []

    try:
        return playwright.chromium.launch(
            channel="msedge",
            headless=True,
        )
    except Exception as exc:
        errors.append(f"msedge channel: {exc}")

    for path in EDGE_CANDIDATES:
        if not str(path) or not path.exists():
            continue
        try:
            return playwright.chromium.launch(
                executable_path=str(path),
                headless=True,
            )
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    raise BrowserToolError(
        "Microsoft Edge could not be launched for read-only browser access. "
        + " | ".join(errors)
    )


def _route_read_only(route, request):
    method = str(request.method or "").upper()
    if method not in {"GET", "HEAD"}:
        route.abort()
        return

    resource_type = str(request.resource_type or "")
    if resource_type in {"websocket", "media", "font"}:
        route.abort()
        return

    parsed = urlparse(request.url)
    if parsed.scheme in {"about", "data", "blob"}:
        route.continue_()
        return

    if parsed.scheme not in {"http", "https"}:
        route.abort()
        return

    if resource_type == "document" and not _is_public_http_url(request.url):
        route.abort()
        return

    route.continue_()


@contextmanager
def _browser_context(timeout_ms=20000):
    with sync_playwright() as playwright:
        browser = _launch_edge(playwright)
        context = browser.new_context(
            accept_downloads=False,
            java_script_enabled=True,
            service_workers="block",
        )
        context.set_default_timeout(timeout_ms)
        context.route("**/*", _route_read_only)
        try:
            yield context
        finally:
            context.close()
            browser.close()


def _page_is_blocked(text):
    normalized = " ".join(str(text or "").lower().split())
    markers = [
        "unusual traffic",
        "verify you are human",
        "captcha",
        "access denied",
        "automated queries",
        "robot check",
    ]
    return any(marker in normalized for marker in markers)


def _parse_bing_results(html_text, limit):
    soup = BeautifulSoup(html_text, "html.parser")
    results = []

    for block in soup.select("li.b_algo, div.b_algo"):
        link = block.select_one("h2 a, h3 a")
        if link is None:
            continue

        title = link.get_text(" ", strip=True)
        url = str(link.get("href", "")).strip()
        snippet_node = block.select_one(".b_caption p, .b_snippet, p")
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

    return results


def browser_search(query, max_results=6, timeout=20.0):
    clean = " ".join(str(query).strip().split())
    if not clean:
        raise BrowserToolError("A browser search query is required.")

    limit = max(1, min(int(max_results or 6), 10))
    url = (
        "https://www.bing.com/search?q="
        + quote_plus(clean)
        + f"&count={limit}"
    )

    with _browser_context(timeout_ms=int(timeout * 1000)) as context:
        page = context.new_page()
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(timeout * 1000),
        )

        if response is not None and response.status >= 400:
            raise BrowserToolError(
                f"Browser search returned HTTP {response.status}."
            )

        page.wait_for_timeout(900)
        body_text = page.locator("body").inner_text(timeout=5000)
        if _page_is_blocked(body_text):
            raise BrowserToolError(
                "Browser search provider requested human verification."
            )

        results = _parse_bing_results(page.content(), limit)
        if not results:
            raise BrowserToolError(
                "Browser search loaded successfully but no usable results were found."
            )

        return {
            "provider": "Edge Browser / Bing",
            "results": results,
        }


def browser_read_html(url, timeout=20.0):
    if not _is_public_http_url(url):
        raise BrowserToolError("Only public http/https pages can be opened.")

    with _browser_context(timeout_ms=int(timeout * 1000)) as context:
        page = context.new_page()
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(timeout * 1000),
        )

        if response is not None and response.status >= 400:
            raise BrowserToolError(
                f"Page returned HTTP {response.status}."
            )

        page.wait_for_timeout(900)
        if not _is_public_http_url(page.url):
            raise BrowserToolError(
                "Page redirected to a non-public address."
            )

        body_text = page.locator("body").inner_text(timeout=5000)
        if _page_is_blocked(body_text):
            raise BrowserToolError(
                "Page requested human verification."
            )

        return page.content()


def browser_read_page(url, timeout=20.0, max_chars=8000):
    if not _is_public_http_url(url):
        raise BrowserToolError("Only public http/https pages can be read.")

    with _browser_context(timeout_ms=int(timeout * 1000)) as context:
        page = context.new_page()
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(timeout * 1000),
        )

        if response is not None and response.status >= 400:
            raise BrowserToolError(
                f"Page returned HTTP {response.status}."
            )

        page.wait_for_timeout(700)
        final_url = page.url
        if not _is_public_http_url(final_url):
            raise BrowserToolError(
                "Page redirected to a non-public address."
            )

        text = page.locator("body").inner_text(timeout=5000)
        if _page_is_blocked(text):
            raise BrowserToolError(
                "Page requested human verification."
            )

        clean = " ".join(text.split())
        return clean[:max_chars]


def browser_read_pages(urls, timeout=20.0, max_chars=8000):
    public_urls = [
        str(url)
        for url in urls
        if _is_public_http_url(url)
    ]
    if not public_urls:
        return {}

    results = {}
    with _browser_context(timeout_ms=int(timeout * 1000)) as context:
        page = context.new_page()

        for url in public_urls[:3]:
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(timeout * 1000),
                )
                if response is not None and response.status >= 400:
                    results[url] = ""
                    continue

                page.wait_for_timeout(600)
                if not _is_public_http_url(page.url):
                    results[url] = ""
                    continue

                text = page.locator("body").inner_text(timeout=5000)
                if _page_is_blocked(text):
                    results[url] = ""
                    continue

                results[url] = " ".join(text.split())[:max_chars]
            except Exception:
                results[url] = ""

    return results
