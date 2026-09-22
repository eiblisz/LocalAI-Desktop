import os

import requests


BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"


class BraveLLMContextError(RuntimeError):
    pass


def _clean(value):
    return " ".join(str(value or "").split())


def context_mode():
    mode = os.environ.get("BRAVE_CONTEXT_MODE", "legacy").strip().lower()
    return mode if mode in {"legacy", "llm_context"} else "legacy"


def _published_from_metadata(metadata):
    value = metadata.get("age") if isinstance(metadata, dict) else ""
    if isinstance(value, (list, tuple)):
        values = [_clean(item) for item in value if _clean(item)]
        return values[-1] if values else ""
    return _clean(value)


def normalize_llm_context_response(payload, *, query, limit):
    payload = dict(payload or {})
    grounding = dict(payload.get("grounding") or {})
    sources = dict(payload.get("sources") or {})
    results = []

    for item in grounding.get("generic") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = _clean(item.get("title"))
        snippets = [
            _clean(value)
            for value in (item.get("snippets") or [])
            if _clean(value)
        ]
        if not url or not title or not snippets:
            continue

        metadata = sources.get(url) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        results.append({
            "title": title,
            "url": url,
            "snippet": snippets[0][:1600],
            "published": _published_from_metadata(metadata),
            "page_text": "\n".join(snippets),
            "source_metadata": {
                key: metadata.get(key)
                for key in (
                    "site_name",
                    "description",
                    "favicon",
                    "thumbnail",
                    "age",
                )
                if metadata.get(key) not in (None, "", [], {})
            },
        })
        if len(results) >= int(limit):
            break

    return {
        "provider": "Brave LLM Context",
        "query": str(query or "").strip(),
        "results": results,
        "pre_extracted_context": True,
        "context_mode": "llm_context",
    }


def search_brave_llm_context(
    query,
    *,
    api_key,
    limit=6,
    timeout=20.0,
    requester=requests.get,
):
    if not str(api_key or "").strip():
        raise BraveLLMContextError("Brave Search API key is not configured.")

    count = max(1, min(int(limit or 6), 50))
    params = {
        "q": str(query or "").strip(),
        "count": count,
        "country": os.environ.get("BRAVE_SEARCH_COUNTRY", "DE").strip().upper() or "DE",
        "maximum_number_of_urls": count,
        "maximum_number_of_tokens": max(
            1024,
            min(
                int(os.environ.get("BRAVE_LLM_CONTEXT_MAX_TOKENS", "8192") or 8192),
                32768,
            ),
        ),
        "context_threshold_mode": (
            os.environ.get("BRAVE_LLM_CONTEXT_THRESHOLD", "strict").strip().lower()
            or "strict"
        ),
        "enable_source_metadata": True,
        "safesearch": "moderate",
    }
    search_lang = os.environ.get("BRAVE_SEARCH_LANG", "").strip()
    if search_lang:
        params["search_lang"] = search_lang

    response = requester(
        BRAVE_LLM_CONTEXT_URL,
        params=params,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": str(api_key).strip(),
        },
        timeout=float(timeout),
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = getattr(response, "status_code", "?")
        code = ""
        detail = ""
        try:
            error = (response.json() or {}).get("error") or {}
            code = _clean(error.get("code"))
            detail = _clean(error.get("detail"))
        except Exception:
            pass
        parts = [f"HTTP {status}"]
        if code:
            parts.append(code)
        if detail:
            parts.append(detail[:280])
        raise BraveLLMContextError(
            "Brave LLM Context: " + ": ".join(parts)
        ) from exc

    payload = response.json()
    normalized = normalize_llm_context_response(
        payload,
        query=query,
        limit=count,
    )
    if not normalized["results"]:
        raise BraveLLMContextError("Brave LLM Context returned no usable grounding.")
    return normalized
