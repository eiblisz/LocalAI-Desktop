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

    # Hungarian country names normally contain "orszag" (for example
    # Nemetorszagban, Magyarorszagon, Franciaorszagbol). Treat those as
    # explicit market authority and do not broaden them automatically.
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
    for line in str(raw or "").splitlines():
        clean = " ".join(line.strip().strip('"\'').split())
        clean = re.sub(r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)", "", clean).strip()
        if clean:
            return clean[:240]
    return ""


def install_bilingual_search_patch(workers_module):
    worker_class = workers_module.ChatWebWorker
    if getattr(worker_class, "_bilingual_search_patch_installed", False):
        return

    original_generate = worker_class._generate_search_queries

    def _generate_german_market_query(self):
        authority = self._search_constraint_authority()
        messages = [
            {
                "role": "system",
                "content": (
                    "Translate the search intent into exactly one concise German-language "
                    "web search query for the German market. Preserve the exact topic, "
                    "product/model names, quantities, dimensions, technical specs, dates, "
                    "numbers, currencies, and price limits. Do not substitute products, "
                    "brands, countries, sizes, or constraints. Add Deutschland as a market "
                    "signal when appropriate. Return ONLY the query, with no numbering, "
                    "quotes, commentary, or explanation."
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
            return ""

        query = _clean_query_line(raw)
        if not query:
            return ""

        query = self._preserve_search_constraints(query)
        if "deutschland" not in self._fold_text(query):
            query = f"{query} Deutschland".strip()
        return query[:260]

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

        # Keep the user's Hungarian shopping request as canonical authority. The
        # German expansion is additive only, so it cannot replace or relax it.
        hungarian_query = self._preserve_search_constraints(
            self._search_constraint_authority()
        )
        german_query = _generate_german_market_query(self)

        queries = [hungarian_query]
        if (
            german_query
            and self._fold_text(german_query) != self._fold_text(hungarian_query)
        ):
            queries.append(german_query)
        return queries[:2]

    worker_class._generate_german_market_query = _generate_german_market_query
    worker_class._generate_search_queries = _generate_search_queries
    worker_class._bilingual_search_patch_installed = True
