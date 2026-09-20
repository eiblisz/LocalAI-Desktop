import json
import re
import unicodedata
from urllib.parse import parse_qs, urlparse


BILINGUAL_QUERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hu_query", "de_query"],
    "properties": {
        "hu_query": {"type": "string", "minLength": 1, "maxLength": 260},
        "de_query": {"type": "string", "minLength": 1, "maxLength": 260},
    },
}


def _fold_token(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    ascii_text = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_text)


def _kit_total_capacity(exact_kit):
    match = re.fullmatch(
        r"(\d+)x(\d+)(gb|tb)",
        str(exact_kit or "").strip().lower(),
    )
    if not match:
        return ""
    count = int(match.group(1))
    size = int(match.group(2))
    unit = match.group(3).upper()
    return f"{count * size}{unit}"


def _is_memory_kit_plan(plan):
    return bool(
        plan.get("exact_kit")
        and plan.get("memory_type")
        and plan.get("speed_mhz") is not None
    )


def is_generic_shopping_url(url):
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False

    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower().rstrip("/")
    query = parse_qs(parsed.query)

    if not host:
        return False
    if "ebay." in host and (
        path.startswith("/sch") or "_nkw" in query
    ):
        return True
    if "amazon." in host and (
        path in {"/s", "/gp/search"} or "k" in query
    ):
        return True
    if path in {"/search", "/suche", "/shop/search", "/products/search"}:
        return True
    if {"search", "query", "keyword", "keywords"}.intersection(query):
        return True
    return False


def specialize_provider_query(
    plan,
    base,
    *,
    query_terms,
    normalized_spec_text,
    format_exact_kit,
):
    if not _is_memory_kit_plan(plan):
        return base

    parts = []
    exact_kit = format_exact_kit(plan.get("exact_kit"))
    if exact_kit:
        parts.append(exact_kit)

    total_capacity = _kit_total_capacity(plan.get("exact_kit"))
    if total_capacity:
        parts.append(total_capacity)

    memory_type = str(plan.get("memory_type") or "").upper()
    if memory_type:
        parts.append(memory_type)

    speed_mhz = plan.get("speed_mhz")
    if speed_mhz is not None:
        parts.append(f"{int(speed_mhz)} MHz")

    ignored_topic_tokens = {
        "mhz", "mts", "mtps", "eur", "usd", "gb", "tb", "ram",
    }
    topic_terms = []
    for term in query_terms(plan.get("query") or ""):
        normalized = normalized_spec_text(term)
        if normalized in {
            normalized_spec_text(plan.get("exact_kit")),
            normalized_spec_text(plan.get("memory_type")),
            str(speed_mhz or ""),
        }:
            continue
        if term.isdigit() or normalized in ignored_topic_tokens:
            continue
        if term not in topic_terms:
            topic_terms.append(term)
        if len(topic_terms) >= 3:
            break

    parts.extend(topic_terms)
    parts.extend(["RAM", "kit", "kaufen"])
    if plan.get("country") == "DE":
        parts.extend(["Germany", "Deutschland"])
    if plan.get("max_price") is not None and plan.get("currency"):
        amount = float(plan["max_price"])
        display = str(int(amount)) if amount.is_integer() else str(amount)
        parts.append(f"under {display} {plan['currency']}")

    canonical = " ".join(
        str(value).strip() for value in parts if str(value).strip()
    )
    return canonical[:260] or base


def _shopping_topic_terms(query, query_terms):
    ignored = {
        "eur", "usd", "under", "below", "maximum", "max", "alatt",
        "felett", "unter", "uber", "ueber", "deutschland", "germany",
        "kaufen", "buy", "shop", "offer", "angebot", "angebote",
    }
    terms = []
    for term in query_terms(query):
        folded = _fold_token(term)
        if term.isdigit() or folded in ignored:
            continue
        if folded and folded not in terms:
            terms.append(folded)
    return terms[:4]


def _has_exact_topic_token(query, item, query_terms):
    topic_terms = _shopping_topic_terms(query, query_terms)
    if not topic_terms:
        return True
    evidence = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("page_text", "")),
    ]).lower()
    evidence_tokens = {
        _fold_token(token)
        for token in re.findall(r"\w+", evidence, flags=re.UNICODE)
        if token
    }
    return any(term in evidence_tokens for term in topic_terms)


def filter_relevant_results(
    query,
    results,
    *,
    plan,
    require_verified,
    base_filter,
    query_terms,
    validate_result_against_plan,
):
    bounded_results = list(results)
    if _is_memory_kit_plan(plan):
        product_results = [
            item for item in bounded_results
            if not is_generic_shopping_url(item.get("url", ""))
        ]
        if product_results:
            bounded_results = product_results
    elif plan.get("max_price") is not None:
        bounded_results = [
            item for item in bounded_results
            if _has_exact_topic_token(query, item, query_terms)
        ]
        validated_results = []
        for item in bounded_results:
            valid, _reasons = validate_result_against_plan(
                plan,
                item,
                require_verified=require_verified,
            )
            if valid:
                validated_results.append(item)
        return validated_results

    return base_filter(
        query,
        bounded_results,
        plan=plan,
        require_verified=require_verified,
    )


def _looks_hungarian(worker):
    text = worker._fold_text(worker.user_prompt)
    markers = [
        "keress", "keresd", "nezd meg", "nekem", "alatt", "felett",
        "mennyibe", "milyen", "kaphato", "ajanlat", "arak", "termek",
        "teas", "kanna", "memoria", "videokartya",
    ]
    padded = f" {text} "
    return any(marker in padded for marker in markers)


def _looks_like_shopping_request(worker):
    text = worker._fold_text(worker.user_prompt)
    padded = f" {text} "
    if re.search(r"(?:€|\$)|\b\d+(?:[.,]\d+)?\s*(?:eur|usd)\b", text):
        return True
    markers = [
        " ar ", " ara ", " arak ", " mennyibe ", " alatt ", " felett ",
        " olcso", " ajanlat", " kaphato", " vasar", " megven", " venni ",
        " webshop", " bolt ", " termek", " kit ", " keszlet", " price ",
        " buy ", " shop ", " offer ",
    ]
    return any(marker in padded for marker in markers)


def _has_explicit_market(worker):
    text = worker._fold_text(worker.user_prompt)
    if re.search(r"\b[a-z0-9]*orszag[a-z0-9]*\b", text):
        return True
    markers = [
        "germany", "deutschland", "hungary", "austria", "osterreich",
        "switzerland", "schweiz", "romania", "slovakia", "slovenia",
        "croatia", "poland", "polska", "france", "italy", "italia",
        "spain", "espana", "netherlands", "nederland", "belgium",
        "belgique", "czechia", "cesko", "uk ", "united kingdom",
        "united states", " usa ", "site:",
    ]
    padded = f" {text} "
    return any(marker in padded for marker in markers)


def _clean_query_line(raw):
    clean = " ".join(str(raw or "").strip().strip("\"'").split())
    clean = re.sub(r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)", "", clean).strip()
    clean = re.sub(r"^(?:HU|DE)\s*:\s*", "", clean, flags=re.IGNORECASE)
    return clean[:240]


def _verified_value(fields, name):
    field = (fields or {}).get(name) or {}
    if field.get("status") != "VERIFIED":
        return None
    return field.get("value")


class WebResearchPipeline:
    """Explicit web-research policy composition used by ChatWebWorker."""

    def __init__(self, worker):
        self.worker = worker

    def generate_bilingual_market_queries(self):
        worker = self.worker
        authority = worker._search_constraint_authority()
        messages = [
            {
                "role": "system",
                "content": (
                    "Create exactly two concise shopping web search queries for the SAME "
                    "product intent. hu_query must use natural Hungarian product terminology "
                    "suitable for Hungarian shops. de_query must use natural German product "
                    "terminology suitable for German shops, adding Deutschland as a market "
                    "signal. Preserve the exact product identity, quantities, dimensions, "
                    "technical specs, dates, numbers, currencies, and price limits. "
                    "Normalize Hungarian inflected wording into the normal product noun "
                    "when useful. Never substitute the product, brand, size, specification, "
                    "or price constraint. Return only the exact JSON object required by "
                    "the supplied schema."
                ),
            },
            {
                "role": "user",
                "content": f"SEARCH AUTHORITY:\n{authority}",
            },
        ]
        try:
            raw = worker.client.chat_once(
                model=worker.model,
                messages=messages,
                response_format=BILINGUAL_QUERY_SCHEMA,
            ).strip()
            document = json.loads(raw)
            if not isinstance(document, dict) or set(document) != {
                "hu_query", "de_query",
            }:
                raise ValueError("Bilingual query plan has invalid keys.")
            hu_query = _clean_query_line(document["hu_query"])
            de_query = _clean_query_line(document["de_query"])
            if not hu_query or not de_query:
                raise ValueError("Bilingual query plan contains an empty query.")
        except Exception as exc:
            raise RuntimeError(
                "Bilingual shopping query planning failed closed."
            ) from exc

        hu_query = worker._preserve_search_constraints(hu_query)
        de_query = worker._preserve_search_constraints(de_query)
        if "deutschland" not in worker._fold_text(de_query):
            de_query = f"{de_query} Deutschland".strip()[:260]

        queries = []
        for query in [hu_query, de_query]:
            if query and worker._fold_text(query) not in {
                worker._fold_text(item) for item in queries
            }:
                queries.append(query[:260])
        if len(queries) != 2:
            raise RuntimeError(
                "Bilingual shopping query planning did not produce two distinct queries."
            )
        return queries

    def generate_search_queries(self, legacy_generate):
        worker = self.worker
        should_expand = (
            _looks_hungarian(worker)
            and _looks_like_shopping_request(worker)
            and not worker._needs_previous_search_context()
            and not worker._has_multiple_research_topics()
            and not _has_explicit_market(worker)
        )
        if should_expand:
            return self.generate_bilingual_market_queries()
        return legacy_generate()

    def deterministic_verified_answer(self, ledgers):
        worker = self.worker
        accepted = [
            ledger for ledger in list(ledgers or [])
            if ledger.get("verdict") == "ACCEPT"
        ]
        if not accepted:
            return ""

        hungarian = "Hungarian" in worker._conversation_language_instruction()
        lines = [
            (
                "Az ellenorzott forrasok alapjan:"
                if hungarian
                else "Based on the verified sources:"
            ),
            "",
        ]

        for index, ledger in enumerate(accepted[:6], start=1):
            fields = ledger.get("fields") or {}
            title = " ".join(
                str(ledger.get("title") or "Verified product").split()
            )
            url = str(
                _verified_value(fields, "url") or ledger.get("url") or ""
            ).strip()
            exact_kit = _verified_value(fields, "exact_kit")
            memory_type = _verified_value(fields, "memory_type")
            speed = _verified_value(fields, "speed_mhz")
            country = _verified_value(fields, "country")
            price = _verified_value(fields, "price")
            currency = str(
                (ledger.get("plan") or {}).get("currency") or ""
            ).strip()

            verified_parts = []
            if exact_kit is not None:
                verified_parts.append(str(exact_kit))
            if memory_type is not None:
                verified_parts.append(str(memory_type).upper())
            if speed is not None:
                verified_parts.append(f"{int(speed)} MHz")
            if country is not None:
                verified_parts.append(str(country))
            if isinstance(price, (int, float)):
                verified_parts.append(
                    f"{float(price):.2f} {currency}".strip()
                )

            lines.append(f"{index}. {title}")
            if verified_parts:
                label = "Ellenorzott adatok" if hungarian else "Verified fields"
                lines.append(f"   {label}: " + " | ".join(verified_parts))
            if url:
                lines.append(f"   Link: {url}")
            lines.append("")

        return "\n".join(lines).strip()

    def safe_evidence_failure(self, *, answer_rejected, ledgers, legacy_failure):
        if answer_rejected:
            fallback = self.deterministic_verified_answer(ledgers)
            if fallback:
                return fallback
        return legacy_failure(answer_rejected=answer_rejected)
