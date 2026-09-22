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



def compact_evidence_authority(
    payload,
    *,
    authoritative_fact=None,
    max_sources=5,
    max_text_chars=700,
):
    """
    Build a bounded provider-neutral evidence authority for factual verification.

    Prefer provider snippets because they are already relevance-focused. Fall back
    to only a short prefix of fetched/page context when no snippet is available.
    The full page text remains available to the initial grounded generation, but
    is deliberately excluded from the verifier to reduce evidence noise.
    """
    provider = _clean(payload.get("provider"))
    query = _clean(payload.get("query"))
    retrieved_at = _clean(payload.get("retrieved_at"))
    lines = [
        f"Provider: {provider}",
        f"Query: {query}",
        f"Retrieved: {retrieved_at}",
    ]

    fact = dict(authoritative_fact or {})
    if fact.get("value"):
        lines.extend([
            "",
            "AUTHORITATIVE CURRENT FACT",
            f"Kind: {_clean(fact.get('kind'))}",
            f"Value: {_clean(fact.get('value'))}",
            f"Authority: {_clean(fact.get('authority'))}",
            f"Source: {_clean(fact.get('title'))}",
            f"Source URL: {str(fact.get('url') or '').strip()}",
        ])

    accepted = 0
    for result in payload.get("results") or []:
        url = str(result.get("url") or "").strip()
        title = _clean(result.get("title"))
        snippet = _clean(result.get("snippet"))
        if snippet:
            relevant = snippet
        else:
            relevant = _clean(result.get("page_text"))

        if not url or not title or not relevant:
            continue

        relevant = relevant[: max(120, int(max_text_chars or 700))].rstrip()
        lines.extend([
            "",
            f"Title: {title}",
            f"URL: {url}",
            f"Relevant text: {relevant}",
        ])
        published = _clean(result.get("published"))
        if published:
            lines.append(f"Published: {published}")

        accepted += 1
        if accepted >= max(1, int(max_sources or 5)):
            break

    return "\n".join(lines).strip() if accepted else ""
