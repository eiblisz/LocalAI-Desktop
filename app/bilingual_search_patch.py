import json
import re


_BILINGUAL_QUERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hu_query", "de_query"],
    "properties": {
        "hu_query": {"type": "string", "minLength": 1, "maxLength": 260},
        "de_query": {"type": "string", "minLength": 1, "maxLength": 260},
    },
}


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
    clean = " ".join(str(raw or "").strip().strip('"\'').split())
    clean = re.sub(r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)", "", clean).strip()
    clean = re.sub(r"^(?:HU|DE)\s*:\s*", "", clean, flags=re.IGNORECASE)
    return clean[:240]


def install_bilingual_search_patch(workers_module):
    worker_class = workers_module.ChatWebWorker
    if getattr(worker_class, "_bilingual_search_patch_installed", False):
        return

    original_generate = worker_class._generate_search_queries

    def _generate_bilingual_market_queries(self):
        authority = self._search_constraint_authority()
        messages = [
            {
                "role": "system",
                "content": (
                    "Create exactly two concise shopping web search queries for the SAME "
                    "product intent. hu_query must use natural Hungarian product terminology "
                    "suitable for Hungarian shops. de_query must use natural German product "
                    "terminology suitable for "
                    "German shops, adding Deutschland as a market signal. Preserve the "
                    "exact product identity, quantities, dimensions, technical specs, "
                    "dates, numbers, currencies, and price limits. Normalize Hungarian "
                    "inflected wording into the normal product noun when useful (for "
                    "example 'teas kannat' -> 'teaskanna'). Never substitute the product, "
                    "brand, size, specification, or price constraint. Return only the exact "
                    "JSON object required by the supplied schema."
                ),
            },
            {
                "role": "user",
                "content": f"SEARCH AUTHORITY:\n{authority}",
            },
        ]
        try:
            raw = self.client.chat_once(
                model=self.model,
                messages=messages,
                response_format=_BILINGUAL_QUERY_SCHEMA,
            ).strip()
            document = json.loads(raw)
            if not isinstance(document, dict) or set(document) != {
                "hu_query",
                "de_query",
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

        if hu_query:
            hu_query = self._preserve_search_constraints(hu_query)
        if de_query:
            de_query = self._preserve_search_constraints(de_query)
            if "deutschland" not in self._fold_text(de_query):
                de_query = f"{de_query} Deutschland".strip()[:260]

        queries = []
        for query in [hu_query, de_query]:
            if query and self._fold_text(query) not in {
                self._fold_text(item) for item in queries
            }:
                queries.append(query[:260])
        if len(queries) != 2:
            raise RuntimeError(
                "Bilingual shopping query planning did not produce two distinct queries."
            )
        return queries

    def _generate_search_queries(self):
        # Decide whether this is an independent bilingual shopping search BEFORE
        # calling the legacy generator. The legacy path can collapse constrained
        # single-topic queries back to the raw authority, which made the later
        # bilingual decision depend on an unnecessary first model call.
        should_expand = (
            _looks_hungarian(self)
            and _looks_like_shopping_request(self)
            and not self._needs_previous_search_context()
            and not self._has_multiple_research_topics()
            and not _has_explicit_market(self)
        )

        if should_expand:
            return _generate_bilingual_market_queries(self)

        return original_generate(self)

    worker_class._generate_bilingual_market_queries = _generate_bilingual_market_queries
    worker_class._generate_search_queries = _generate_search_queries
    worker_class._bilingual_search_patch_installed = True
