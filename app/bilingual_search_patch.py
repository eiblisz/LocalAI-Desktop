import re


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
                    "product intent. Line 1 must start with 'HU:' and use natural Hungarian "
                    "product terminology suitable for Hungarian shops. Line 2 must start "
                    "with 'DE:' and use natural German product terminology suitable for "
                    "German shops, adding Deutschland as a market signal. Preserve the "
                    "exact product identity, quantities, dimensions, technical specs, "
                    "dates, numbers, currencies, and price limits. Normalize Hungarian "
                    "inflected wording into the normal product noun when useful (for "
                    "example 'teas kannat' -> 'teaskanna'). Never substitute the product, "
                    "brand, size, specification, or price constraint. Return ONLY the two "
                    "query lines and no explanation."
                ),
            },
            {
                "role": "user",
                "content": f"SEARCH AUTHORITY:\n{authority}",
            },
        ]
        try:
            raw = self.client.chat_once(model=self.model, messages=messages).strip()
        except Exception:
            return []

        hu_query = ""
        de_query = ""
        for line in raw.splitlines():
            stripped = line.strip()
            if re.match(r"^HU\s*:", stripped, flags=re.IGNORECASE):
                hu_query = _clean_query_line(stripped)
            elif re.match(r"^DE\s*:", stripped, flags=re.IGNORECASE):
                de_query = _clean_query_line(stripped)

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
        return queries[:2]

    def _generate_search_queries(self):
        base_queries = original_generate(self)

        if not _looks_hungarian(self):
            return base_queries
        if not _looks_like_shopping_request(self):
            return base_queries
        if self._needs_previous_search_context():
            return base_queries
        if self._has_multiple_research_topics():
            return base_queries
        if _has_explicit_market(self):
            return base_queries

        localized_queries = _generate_bilingual_market_queries(self)
        if len(localized_queries) == 2:
            return localized_queries

        return base_queries

    worker_class._generate_bilingual_market_queries = _generate_bilingual_market_queries
    worker_class._generate_search_queries = _generate_search_queries
    worker_class._bilingual_search_patch_installed = True
