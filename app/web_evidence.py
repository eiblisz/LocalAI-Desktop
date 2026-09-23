import re

from .text_normalization import canonical_match_text, canonical_tokens


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



def _fold_terms(value):
    return {
        term
        for term in canonical_tokens(value)
        if len(term) >= 3
    }


def _fold_text(value):
    return canonical_match_text(value)


def _temporal_fact_requested(value):
    folded = " " + re.sub(r"\s+", " ", _fold_text(value)).strip() + " "
    markers = (
        " mikor ",
        " mikorra ",
        " melyik ev ",
        " hanyban ",
        " datum ",
        " when ",
        " what year ",
        " which year ",
        " date ",
        " wann ",
        " welches jahr ",
        " in welchem jahr ",
        " datum ",
    )
    return any(marker in folded for marker in markers)


def _contains_temporal_literal(value):
    text = str(value or "")
    return bool(
        re.search(
            r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)"
            r"|\b\d{4}-\d{2}-\d{2}\b"
            r"|\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
            text,
        )
    )


def _page_evidence_excerpt(page_text, prompt_terms, *, temporal_requested=False):
    text = str(page_text or "").strip()
    if not text:
        return ""

    text = text[:24000]
    raw_segments = [
        _clean(segment)
        for segment in re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
        if _clean(segment)
    ]
    if not raw_segments:
        return _clean(text)

    candidates = []
    for index, segment in enumerate(raw_segments):
        windows = [segment]
        if index + 1 < len(raw_segments):
            windows.append(segment + " " + raw_segments[index + 1])
        for window in windows:
            terms = _fold_terms(window)
            overlap = len(prompt_terms.intersection(terms))
            temporal_bonus = (
                6
                if temporal_requested and _contains_temporal_literal(window)
                else 0
            )
            score = (overlap * 3) + temporal_bonus
            candidates.append((score, -index, window))

    candidates.sort(reverse=True)
    best = candidates[0][2] if candidates else ""
    return _clean(best)


def _result_relevant_text(
    result,
    prompt_terms,
    *,
    temporal_requested=False,
    max_chars=420,
):
    snippet = _clean(result.get("snippet"))
    page_excerpt = _page_evidence_excerpt(
        result.get("page_text"),
        prompt_terms,
        temporal_requested=temporal_requested,
    )

    parts = []
    prefer_page = (
        temporal_requested
        and _contains_temporal_literal(page_excerpt)
        and not _contains_temporal_literal(snippet)
    )
    if prefer_page and page_excerpt:
        parts.append("Page evidence: " + page_excerpt)
    if snippet:
        parts.append(snippet)
    if (
        not prefer_page
        and page_excerpt
        and _fold_text(page_excerpt) not in _fold_text(snippet)
        and _fold_text(snippet) not in _fold_text(page_excerpt)
    ):
        parts.append("Page evidence: " + page_excerpt)

    relevant = " | ".join(parts) or page_excerpt
    return relevant[: max(120, int(max_chars or 420))].rstrip()


def compact_evidence_bundle(
    payloads,
    *,
    user_prompt="",
    authoritative_facts=(),
    max_sources=8,
    max_total_chars=7000,
    max_text_chars=420,
):
    """
    Build one globally bounded evidence authority across all search queries.

    The previous verifier concatenated a separate bounded authority per query.
    With up to four searches that could still become large enough to crowd a
    small local-model context window. This bundle ranks provider-neutral
    evidence by overlap with the current request, deduplicates URLs, and applies
    one total character budget across the whole factual verification context.
    """
    prompt_terms = _fold_terms(user_prompt)
    temporal_requested = _temporal_fact_requested(user_prompt)
    candidates = []
    seen_urls = set()
    order = 0

    for payload in list(payloads or []):
        provider = _clean(payload.get("provider"))
        query = _clean(payload.get("query"))
        retrieved_at = _clean(payload.get("retrieved_at"))

        for result in payload.get("results") or []:
            url = str(result.get("url") or "").strip()
            title = _clean(result.get("title"))
            relevant = _result_relevant_text(
                result,
                prompt_terms,
                temporal_requested=temporal_requested,
                max_chars=max_text_chars,
            )
            if not url or not title or not relevant or url in seen_urls:
                continue
            seen_urls.add(url)

            title_terms = _fold_terms(title)
            text_terms = _fold_terms(relevant)
            title_overlap = len(prompt_terms.intersection(title_terms))
            text_overlap = len(prompt_terms.intersection(text_terms))
            score = (title_overlap * 3) + text_overlap

            candidates.append({
                "score": score,
                "order": order,
                "provider": provider,
                "query": query,
                "retrieved_at": retrieved_at,
                "title": title,
                "url": url,
                "relevant": relevant,
                "published": _clean(result.get("published")),
            })
            order += 1

    candidates.sort(key=lambda item: (-item["score"], item["order"]))

    lines = []
    for fact in list(authoritative_facts or []):
        fact = dict(fact or {})
        if not fact.get("value"):
            continue
        lines.extend([
            "AUTHORITATIVE CURRENT FACT",
            f"Kind: {_clean(fact.get('kind'))}",
            f"Value: {_clean(fact.get('value'))}",
            f"Authority: {_clean(fact.get('authority'))}",
            f"Source: {_clean(fact.get('title'))}",
            f"Source URL: {str(fact.get('url') or '').strip()}",
            "",
        ])

    accepted = 0
    budget = max(1200, int(max_total_chars or 7000))
    per_source = max(120, int(max_text_chars or 420))

    for item in candidates:
        if accepted >= max(1, int(max_sources or 8)):
            break

        relevant = item["relevant"][:per_source].rstrip()
        block = [
            f"Provider: {item['provider']}",
            f"Query: {item['query']}",
            f"Retrieved: {item['retrieved_at']}",
            f"Title: {item['title']}",
            f"URL: {item['url']}",
            f"Relevant text: {relevant}",
        ]
        if item["published"]:
            block.append(f"Published: {item['published']}")
        block.append("")

        candidate_text = "\n".join(lines + block).strip()
        if len(candidate_text) > budget:
            if accepted == 0:
                remaining = max(120, budget - len("\n".join(lines)) - 260)
                block[5] = f"Relevant text: {relevant[:remaining].rstrip()}"
                lines.extend(block)
                accepted += 1
            break

        lines.extend(block)
        accepted += 1

    return "\n".join(lines).strip() if accepted or lines else ""
