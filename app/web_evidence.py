def _clean(value):
    return " ".join(str(value or "").split())


def normalized_evidence_items(payload):
    """Provider-neutral evidence contract consumed by orchestration and diagnostics."""
    provider = _clean(payload.get("provider"))
    query = _clean(payload.get("query"))
    retrieved_at = _clean(payload.get("retrieved_at"))
    items = []

    for result in payload.get("results") or []:
        url = str(result.get("url") or "").strip()
        title = _clean(result.get("title"))
        text = str(result.get("page_text") or result.get("snippet") or "").strip()
        if not url or not title or not text:
            continue
        items.append({
            "provider": provider,
            "query": query,
            "retrieved_at": retrieved_at,
            "title": title,
            "url": url,
            "text": text,
            "published": _clean(result.get("published")),
            "authority": _clean(result.get("authority")),
            "source_metadata": dict(result.get("source_metadata") or {}),
        })

    return items
