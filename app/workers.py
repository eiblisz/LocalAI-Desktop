import re
import threading
import unicodedata

from PySide6.QtCore import QObject, Signal, Slot

from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .ebay_tool import ebay_context_text, search_ebay
from .evidence_verifier import (
    evidence_ledger_context_text,
    evidence_required,
    filter_verified_results,
    verify_answer_against_evidence,
)
from .generic_shopping_evidence import (
    build_generic_shopping_queries,
    build_generic_shopping_records,
    is_generic_shopping_request,
    render_generic_shopping_answer,
)
from .memory_runtime import remember_explicit_request
from .language_policy import (
    detect_user_language,
    response_language_instruction,
    response_language_matches,
)
from .ollama_client import OllamaClient
from .weather_tool import get_weather, weather_context_text
from .web_intent import answer_requires_web_fallback
from .web_search_tool import (
    build_search_plan,
    search_web,
    source_entries,
    source_urls,
    web_search_context_text,
)


class ChatWorker(QObject):
    token = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, client: OllamaClient, model: str, messages: list[dict]):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = messages
        self._stop_event = threading.Event()

    @Slot()
    def run(self):
        try:
            self.client.chat_stream(
                model=self.model,
                messages=self.messages,
                on_token=self.token.emit,
                should_stop=self._stop_event.is_set,
            )
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()


class MemoryWriteWorker(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        user_text: str,
        memory_store,
        source_chat_id: str,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.user_text = str(user_text or "").strip()
        self.memory_store = memory_store
        self.source_chat_id = str(source_chat_id or "").strip()
        self.saved_count = 0

    @Slot()
    def run(self):
        try:
            written = remember_explicit_request(
                self.client,
                self.model,
                self.user_text,
                self.memory_store,
                source_chat_id=self.source_chat_id or None,
            )
            self.saved_count = len(written)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        # The extraction call is a bounded non-streaming request and cannot be
        # interrupted safely once submitted. Keep the worker API compatible
        # with MainWindow's shared stop/cleanup path.
        return None


class ChatWebWorker(QObject):
    token = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        messages: list[dict],
        user_prompt: str,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self._stop_event = threading.Event()

    def _recent_user_requests(self, limit=4):
        requests = []
        for message in reversed(self.messages):
            if message.get("role") != "user":
                continue

            text = str(message.get("content", "")).strip()
            if not text or text == self.user_prompt:
                continue

            requests.append(text[:1200])
            if len(requests) >= limit:
                break

        return list(reversed(requests))

    @staticmethod
    def _fold_text(value):
        normalized = unicodedata.normalize(
            "NFKD",
            str(value or "").lower(),
        )
        ascii_text = "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        )
        return " ".join(ascii_text.split())

    def _is_research_followup(self):
        normalized = self._fold_text(self.user_prompt)
        if re.search(r"\bkeress\w*\s+(?:ra\s+)?(?:ujra|megint)\b", normalized):
            return True
        markers = [
            "nezd meg ujra",
            "nezd meg megint",
            "arra keress",
            "erre keress",
            "ugyanazt",
            "ugyan ezt",
            "probald ujra",
            "most ujra",
            "search again",
            "look it up again",
            "try again",
            "same search",
        ]
        return any(marker in normalized for marker in markers)

    def _needs_previous_search_context(self):
        if self._is_research_followup():
            return True

        normalized = self._fold_text(self.user_prompt)
        reference_markers = [
            "ebbol",
            "abbol",
            "ilyet",
            "ilyeneket",
            "azt keress",
            "azokat keress",
            "ezeket keress",
            "ugyanez",
            "ugyanilyet",
            "olcsobbat",
            "dragabbat",
            "masikat",
            "that one",
            "those ones",
            "same one",
            "same thing",
            "cheaper one",
            "more expensive one",
        ]
        return any(marker in normalized for marker in reference_markers)

    def _conversation_language_instruction(self):
        return response_language_instruction(self.user_prompt)

    def _repair_response_language(self, answer):
        if response_language_matches(self.user_prompt, answer):
            return answer

        expected = detect_user_language(self.user_prompt)
        language_name = {
            "hu": "Hungarian",
            "de": "German",
            "en": "English",
        }.get(expected)
        if not language_name:
            return answer

        repaired = self.client.chat_once(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Rewrite the supplied answer in {language_name}. "
                        "Preserve every URL, number, product name, and factual claim exactly. "
                        "Do not add, remove, infer, or correct facts. Return only the rewritten answer."
                    ),
                },
                {
                    "role": "user",
                    "content": answer,
                },
            ],
        ).strip()

        if repaired and response_language_matches(self.user_prompt, repaired):
            return repaired

        if expected == "hu":
            return (
                "A generált webes válasz nyelve nem egyezett a kérdés nyelvével. "
                "A rendszer nem jeleníti meg a hibás nyelvű választ."
            )
        if expected == "de":
            return (
                "Die Sprache der generierten Web-Antwort stimmte nicht mit der "
                "Sprache der Anfrage überein. Die fehlerhafte Antwort wird nicht angezeigt."
            )
        return (
            "The generated web answer used the wrong language and was not shown."
        )

    def _query_is_literal_followup_command(self, query):
        normalized = self._fold_text(query)
        if re.search(r"\bkeress\w*\s+(?:ra\s+)?(?:ujra|megint)\b", normalized):
            return True
        bad_markers = [
            "nezd meg ujra",
            "nezd meg megint",
            "search again",
            "look it up again",
            "try again",
            "same search",
        ]
        return any(marker in normalized for marker in bad_markers)

    def _search_constraint_authority(self):
        source = self.user_prompt
        if self._is_research_followup():
            recent = self._recent_user_requests(limit=1)
            if recent:
                source = recent[-1]
        return " ".join(str(source or "").split())

    def _required_search_constraints(self):
        source = self._search_constraint_authority()

        patterns = [
            r"\b\d+\s*[x×]\s*\d+\s*(?:GB|TB)\b",
            r"\bDDR\s*[345]\b",
            r"\b\d{3,5}\s*(?:MHz|MT/s|MTs|MTPS)\b",
            r"\b\d+(?:[.,]\d+)?\s*(?:EUR|USD)\b",
            r"(?:€|\$)\s*\d+(?:[.,]\d+)?\b",
        ]
        constraints = []
        for pattern in patterns:
            for match in re.finditer(pattern, source, flags=re.IGNORECASE):
                clean = " ".join(match.group(0).split())
                if clean not in constraints:
                    constraints.append(clean)
        return constraints

    def _has_multiple_research_topics(self):
        normalized = self._fold_text(self.user_prompt)
        command_patterns = [
            r"\bkeress\w*\b",
            r"\bnezd\s+meg\b",
            r"\bsearch\b",
            r"\bfind\b",
            r"\blook\s+up\b",
        ]
        command_count = sum(
            len(re.findall(pattern, normalized, flags=re.IGNORECASE))
            for pattern in command_patterns
        )
        return command_count >= 2

    def _preserve_search_constraints(self, query):
        clean = " ".join(str(query or "").split())
        folded = self._fold_text(clean)
        for constraint in self._required_search_constraints():
            if self._fold_text(constraint) not in folded:
                clean = f"{clean} {constraint}".strip()
                folded = self._fold_text(clean)
        return clean[:260]

    @staticmethod
    def _compact_web_error(exc, limit=360):
        message = " ".join(str(exc or "").split())
        if len(message) <= limit:
            return message
        return message[: max(0, limit - 3)].rstrip() + "..."

    def _generate_search_queries(self):
        prompt = self.user_prompt[:5000]
        use_previous_context = self._needs_previous_search_context()
        recent_requests = (
            self._recent_user_requests()
            if use_previous_context
            else []
        )
        history_text = "\n\n".join(
            f"PREVIOUS USER REQUEST {index + 1}:\n{text}"
            for index, text in enumerate(recent_requests)
        )

        followup_rule = ""
        if self._is_research_followup():
            followup_rule = (
                "IMPORTANT: The current request is a follow-up asking to search again. "
                "Resolve words such as 'again', 'same', 'arra', 'erre', 'újra', or "
                "'megint' from the PREVIOUS USER REQUESTS. Never treat the literal "
                "phrase 'keress rá újra' / 'search again' as a title, person, book, "
                "movie, or search subject. Re-run the actual previous research topic, "
                "preserving its product specs, quantities, price limits, location, and "
                "other constraints. "
            )
        elif use_previous_context:
            followup_rule = (
                "IMPORTANT: The current request contains a reference to an earlier "
                "request. Use PREVIOUS USER REQUESTS only to resolve that reference. "
                "The CURRENT USER REQUEST remains authoritative and must not be replaced "
                "by an older topic. "
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the CURRENT USER REQUEST into between one and four concise "
                    "web search queries. Use PREVIOUS USER REQUESTS only to resolve "
                    "references and follow-up wording. "
                    + followup_rule
                    + "If the user asks several distinct research questions, return one "
                    "query for each question. Preserve product names, model names, memory "
                    "sizes, places, dates, price constraints, and other important details. "
                    "Prefer English search terms when that improves international results. "
                    "Return ONLY the queries, one per line, with no numbering, bullets, "
                    "quotes, commentary, guessed media/book categories, or explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{history_text}\n\n" if history_text else ""
                )
                + f"CURRENT USER REQUEST:\n{prompt}",
            },
        ]

        raw = self.client.chat_once(
            model=self.model,
            messages=messages,
        ).strip()

        queries = []
        for line in raw.splitlines():
            clean = " ".join(line.strip().strip('\"\'').split())
            clean = re.sub(
                r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)",
                "",
                clean,
            ).strip()
            if (
                clean
                and clean not in queries
                and not (
                    self._is_research_followup()
                    and self._query_is_literal_followup_command(clean)
                )
            ):
                queries.append(clean[:260])
            if len(queries) >= 4:
                break

        if (
            len(queries) > 1
            and self._required_search_constraints()
            and not self._has_multiple_research_topics()
        ):
            authority = self._search_constraint_authority()
            return [self._preserve_search_constraints(authority)]

        if not queries:
            if self._is_research_followup() and recent_requests:
                queries = [self._preserve_search_constraints(recent_requests[-1])]
            else:
                queries = [self._preserve_search_constraints(self.user_prompt)]
        elif len(queries) == 1:
            queries = [self._preserve_search_constraints(queries[0])]
        return queries

    def _safe_evidence_failure(self, answer_rejected=False):
        if "Hungarian" in self._conversation_language_instruction():
            if answer_rejected:
                return (
                    "Az ellenorzesi lepes elutasitotta a generalt valaszt, mert olyan "
                    "arat, specifikaciot vagy linket tartalmazott, amelyet a bizonyitekok "
                    "nem igazoltak. Inkabb nem jelenitek meg bizonytalan ajanlast."
                )
            return (
                "Nem talaltam eleg termekszintu bizonyitekot olyan ajanlathoz, amely "
                "egyszerre teljesiti az osszes kert hard feltetelt. A rendszer nem "
                "jelenit meg nem ellenorzott termeket, arat vagy specifikaciot."
            )
        if answer_rejected:
            return (
                "The generated answer was rejected because it contained a price, "
                "specification, or link that was not verified by the evidence. "
                "I will not show an unverified recommendation."
            )
        return (
            "I could not find enough product-level evidence for an offer that satisfies "
            "all requested hard constraints. Unverified products, prices, and "
            "specifications are not shown."
        )

    @staticmethod
    def _evidence_diagnostic(ledgers, limit=6):
        lines = []
        for index, ledger in enumerate(list(ledgers or [])[:limit], start=1):
            fields = ledger.get("fields") or {}
            issues = []
            for name in ledger.get("required") or []:
                field = fields.get(name) or {}
                status = str(field.get("status") or "UNKNOWN")
                if status == "VERIFIED":
                    continue
                reason = " ".join(str(field.get("evidence") or "no evidence").split())
                if len(reason) > 90:
                    reason = reason[:87].rstrip() + "..."
                issues.append(f"{name}={status} ({reason})")

            if not issues:
                continue

            lines.append(
                f"Candidate {index} -> "
                + "; ".join(issues[:4])
            )
        return "\n".join(lines)

    @Slot()
    def run(self):
        try:
            if not self.user_prompt:
                raise RuntimeError("Web chat request is empty.")

            generic_shopping_mode = (
                is_generic_shopping_request(self.user_prompt)
                and not self._has_multiple_research_topics()
                and not evidence_required(build_search_plan(self.user_prompt))
            )
            queries = (
                build_generic_shopping_queries(self.user_prompt)
                if generic_shopping_mode
                else self._generate_search_queries()
            )
            generic_shopping_records = []
            generic_shopping_queries = []
            generic_shopping_providers = []
            contexts = []
            urls = []
            entries = []
            successful_queries = []
            successful_providers = []
            provider_fallback_notes = []
            failed_queries = []
            evidence_ledgers = []
            verification_queries = []
            constrained_rejections = []

            for query in queries:
                if self._stop_event.is_set():
                    self.finished.emit()
                    return

                try:
                    payload = search_web(
                        query,
                        max_results=10 if generic_shopping_mode else 6,
                        fetch_pages=True,
                    )
                except Exception as exc:
                    failed_queries.append(
                        f"{query}: {self._compact_web_error(exc)}"
                    )
                    continue

                if generic_shopping_mode:
                    if query not in generic_shopping_queries:
                        generic_shopping_queries.append(query)
                    provider = str(payload.get("provider", "")).strip() or "unknown"
                    if provider not in generic_shopping_providers:
                        generic_shopping_providers.append(provider)
                    for note in payload.get("provider_chain_errors") or []:
                        if note not in provider_fallback_notes:
                            provider_fallback_notes.append(str(note))

                    records = build_generic_shopping_records(
                        query,
                        payload.get("results") or [],
                        limit=6,
                    )
                    known_urls = {
                        item["url"] for item in generic_shopping_records
                    }
                    for record in records:
                        if record["url"] not in known_urls:
                            generic_shopping_records.append(record)
                            known_urls.add(record["url"])
                    if not records:
                        failed_queries.append(
                            f"{query}: no product-specific shopping evidence"
                        )
                    continue

                context_body = web_search_context_text(payload)
                if isinstance(payload.get("search_plan"), dict):
                    verified_results, ledgers, constrained = filter_verified_results(
                        query,
                        payload.get("results") or [],
                    )
                    if constrained:
                        evidence_ledgers.extend(ledgers)
                        payload = dict(payload)
                        payload["results"] = verified_results
                        if not verified_results:
                            constrained_rejections.append(query)
                            failed_queries.append(
                                f"{query}: no product-specific evidence passed hard constraints"
                            )
                            continue
                        verification_queries.append(query)
                        context_body = evidence_ledger_context_text(payload)

                query_urls = source_urls(payload)
                if not query_urls:
                    failed_queries.append(
                        f"{query}: no usable public sources"
                    )
                    continue

                successful_queries.append(query)
                provider = str(payload.get("provider", "")).strip() or "unknown"
                if provider not in successful_providers:
                    successful_providers.append(provider)
                for note in payload.get("provider_chain_errors") or []:
                    if note not in provider_fallback_notes:
                        provider_fallback_notes.append(str(note))
                contexts.append(
                    f"SEARCH QUERY: {query}\n"
                    f"{context_body}"
                )
                for url in query_urls:
                    if url not in urls:
                        urls.append(url)

                for entry in source_entries(payload, limit=6):
                    if entry["url"] not in {
                        item["url"] for item in entries
                    }:
                        entries.append(entry)

            if generic_shopping_mode:
                answer = render_generic_shopping_answer(
                    self.user_prompt,
                    generic_shopping_records,
                )
                self.token.emit(answer)

                if generic_shopping_queries:
                    if len(generic_shopping_queries) == 1:
                        query_footer = (
                            f"Search query: {generic_shopping_queries[0]}"
                        )
                    else:
                        query_footer = (
                            "Search queries:\n"
                            + "\n".join(
                                f"- {query}"
                                for query in generic_shopping_queries
                            )
                        )
                else:
                    query_footer = f"Search query: {self.user_prompt}"

                if len(generic_shopping_providers) == 1:
                    provider_footer = (
                        f"Search provider: {generic_shopping_providers[0]}"
                    )
                elif generic_shopping_providers:
                    provider_footer = (
                        "Search providers: "
                        + ", ".join(generic_shopping_providers)
                    )
                else:
                    provider_footer = "Search provider: none"

                if generic_shopping_records:
                    source_lines = "\n".join(
                        f"- [{item['title']}]({item['url']})"
                        for item in generic_shopping_records[:12]
                    )
                    evidence_status = (
                        "Shopping evidence: PASS "
                        f"({len(generic_shopping_records)} product-level result(s))"
                    )
                else:
                    source_lines = "- No verified product-level source"
                    evidence_status = (
                        "Shopping evidence: FAIL-CLOSED "
                        "(0 product-level results)"
                    )

                self.token.emit(
                    "\n\n---\n"
                    f"{query_footer}\n"
                    f"{provider_footer}\n"
                    f"{evidence_status}\n"
                    "Web results / sources:\n"
                    f"{source_lines}"
                )
                self.finished.emit()
                return

            if not contexts or not urls:
                if constrained_rejections:
                    diagnostic = self._evidence_diagnostic(evidence_ledgers)
                    diagnostic_text = (
                        "\nEvidence diagnostic:\n" + diagnostic
                        if diagnostic
                        else ""
                    )
                    self.token.emit(self._safe_evidence_failure())
                    self.token.emit(
                        "\n\n---\n"
                        f"Search query: {constrained_rejections[0]}\n"
                        "Evidence verification: FAIL-CLOSED (0 accepted products)"
                        f"{diagnostic_text}"
                    )
                    self.finished.emit()
                    return

                detail = " | ".join(failed_queries[:4])
                raise RuntimeError(
                    "Web research returned no usable public sources."
                    + (f" {detail}" if detail else "")
                )

            history = [dict(message) for message in self.messages]
            if history and history[-1].get("role") == "user":
                history = history[:-1]

            base_history = []
            conversation_history = []
            if history and history[0].get("role") == "system":
                base_history = [history[0]]
                prior_messages = history[1:]
            else:
                prior_messages = history

            if self._needs_previous_search_context():
                conversation_history = [
                    message
                    for message in prior_messages
                    if message.get("role") in {"user", "assistant"}
                ][-6:]

            grounded_system = {
                "role": "system",
                "content": (
                    "This response uses read-only web research. For current or external "
                    "facts, use ONLY the AUTHORIZED WEB TOOL DATA in the final user "
                    "message. Do not use memory to fill missing current facts. Answer "
                    "every distinct part of the user's request separately when possible. "
                    "If one part has no supporting source, say that explicitly for that "
                    "part instead of inventing an answer. Never invent prices, "
                    "specifications, dates, availability, ratings, comparisons, or "
                    "quotations. Do not answer an adjacent topic. When VERIFIED WEB "
                    "EVIDENCE LEDGER data is present, mention only ACCEPT results and "
                    "only fields explicitly marked VERIFIED. When you mention a specific "
                    "product, offer, article, or result, include its provided source URL "
                    "in the same bullet or sentence using Markdown link syntax. Do not "
                    "say you cannot browse the web; the authorized web data has already "
                    "been collected for you. "
                    + self._conversation_language_instruction()
                ),
            }

            context_text = "\n\n===== NEXT SEARCH =====\n\n".join(contexts)
            failure_text = ""
            if failed_queries:
                failure_text = (
                    "\n\nSEARCHES WITHOUT USABLE SOURCES:\n- "
                    + "\n- ".join(failed_queries[:4])
                )

            grounded_user = {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{self.user_prompt}\n\n"
                    f"AUTHORIZED WEB TOOL DATA:\n{context_text}"
                    f"{failure_text}"
                ),
            }

            stream_messages = (
                base_history
                + [grounded_system]
                + conversation_history
                + [grounded_user]
            )

            answer_parts = []
            self.client.chat_stream(
                model=self.model,
                messages=stream_messages,
                on_token=answer_parts.append,
                should_stop=self._stop_event.is_set,
            )

            if self._stop_event.is_set():
                self.finished.emit()
                return

            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("The model returned an empty web answer.")

            answer = self._repair_response_language(answer)

            verification_status = ""
            unique_verification_queries = list(dict.fromkeys(verification_queries))
            if len(unique_verification_queries) == 1:
                valid, reasons = verify_answer_against_evidence(
                    answer,
                    unique_verification_queries[0],
                    evidence_ledgers,
                )
                if not valid:
                    answer = self._safe_evidence_failure(answer_rejected=True)
                    verification_status = (
                        "Answer verification: FAIL-CLOSED ("
                        + ", ".join(reasons[:3])
                        + ")"
                    )
                else:
                    verification_status = "Evidence + answer verification: PASS"

            self.token.emit(answer)

            if entries:
                source_lines = "\n".join(
                    f"- [{item['title']}]({item['url']})"
                    for item in entries[:12]
                )
            else:
                source_lines = "\n".join(
                    f"- {url}" for url in urls[:12]
                )

            if len(successful_queries) == 1:
                query_footer = f"Search query: {successful_queries[0]}"
            else:
                query_footer = (
                    "Search queries:\n"
                    + "\n".join(
                        f"- {query}" for query in successful_queries
                    )
                )

            if len(successful_providers) == 1:
                provider_footer = f"Search provider: {successful_providers[0]}"
            else:
                provider_footer = (
                    "Search providers: "
                    + ", ".join(successful_providers)
                )

            fallback_footer = ""
            brave_fallback = [
                note for note in provider_fallback_notes
                if note.startswith("Brave Search API:")
            ]
            if brave_fallback:
                fallback_footer = (
                    "\nBrave fallback: "
                    + brave_fallback[0].split(":", 1)[1].strip()
                )

            verification_footer = (
                f"\n{verification_status}"
                if verification_status
                else ""
            )

            self.token.emit(
                "\n\n---\n"
                f"{query_footer}\n"
                f"{provider_footer}"
                f"{fallback_footer}"
                f"{verification_footer}\n"
                "Web results / sources:\n"
                f"{source_lines}"
            )
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()


def run_chat_web_request(client, model, messages, user_prompt):
    """Run the existing grounded web worker synchronously and collect its answer."""
    chunks = []
    errors = []
    worker = ChatWebWorker(
        client,
        model,
        messages,
        user_prompt,
    )
    worker.token.connect(chunks.append)
    worker.failed.connect(errors.append)
    worker.run()

    if errors:
        raise RuntimeError(errors[0])

    answer = "".join(chunks).strip()
    if not answer:
        raise RuntimeError("Web research returned an empty answer.")
    return answer


class AdaptiveChatWorker(QObject):
    """
    Normal local chat with one bounded automatic web fallback.

    The first pass stays fully local. If the model explicitly reports missing or
    stale knowledge, the worker discards that draft and retries once through the
    existing grounded WEB AUTO runtime.
    """

    token = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        messages: list[dict],
        user_prompt: str,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self._stop_event = threading.Event()
        self.used_web_fallback = False

    @Slot()
    def run(self):
        try:
            if self._stop_event.is_set():
                self.finished.emit()
                return

            draft = self.client.chat_once(
                model=self.model,
                messages=self.messages,
            ).strip()

            if (
                not self._stop_event.is_set()
                and answer_requires_web_fallback(self.user_prompt, draft)
            ):
                self.used_web_fallback = True
                final = run_chat_web_request(
                    self.client,
                    self.model,
                    self.messages,
                    self.user_prompt,
                ).strip()
            else:
                final = draft

            if self._stop_event.is_set():
                self.finished.emit()
                return

            if final:
                self.token.emit(final)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()


class DocumentWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, client: OllamaClient, model: str, messages: list[dict]):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = messages

    @Slot()
    def run(self):
        try:
            content = self.client.chat_once(
                model=self.model,
                messages=self.messages,
            )
            if not content.strip():
                raise RuntimeError("The model returned an empty document.")
            self.finished.emit(content)
        except Exception as exc:
            self.failed.emit(str(exc))


class ScheduledTaskWorker(QObject):
    finished = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, client: OllamaClient, task: dict):
        super().__init__()
        self.client = client
        self.task = dict(task)
        self.source_urls = []
        self.effective_query = ""

    def _generate_search_query(self, prompt, model):
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the user's scheduled research task into one concise web "
                    "search query. Preserve product/model/proper names. Prefer English "
                    "search terms when that improves international web results. "
                    "Return ONLY the search query, no explanation, no quotes."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        query = self.client.chat_once(
            model=model,
            messages=messages,
        ).strip()
        query = " ".join(query.splitlines()[0].strip().strip('\"\'').split())
        return query[:180] or prompt[:180]

    def _build_context(self, model):
        task_type = str(self.task.get("task_type", "weather")).strip().lower()

        if task_type == "weather":
            location = str(self.task.get("location", "")).strip()
            if not location:
                raise RuntimeError("Weather task requires a location.")
            weather = get_weather(location)
            return weather_context_text(weather)

        if task_type == "ebay":
            query = str(self.task.get("ebay_query", "")).strip()
            prompt_query = str(self.task.get("prompt", "")).strip()
            if not query or query.lower() in {"ebay", "ebay.de"}:
                query = prompt_query
            if not query:
                raise RuntimeError("eBay Search task requires a query or prompt.")
            payload = search_ebay(
                query,
                max_results=int(self.task.get("ebay_max_results", 8) or 8),
            )
            self.source_urls = [
                str(item.get("url", "")).strip()
                for item in payload.get("results") or []
                if str(item.get("url", "")).strip()
            ]
            self.effective_query = query
            return ebay_context_text(payload)

        if task_type == "computer":
            return computer_status_context_text(get_computer_status())

        if task_type == "custom":
            if not bool(self.task.get("web_search_enabled", False)):
                return ""

            query = str(self.task.get("web_query", "")).strip()
            if not query:
                query = self._generate_search_query(
                    str(self.task.get("prompt", "")).strip(),
                    model,
                )

            payload = search_web(
                query,
                max_results=int(self.task.get("web_max_results", 6) or 6),
                fetch_pages=bool(self.task.get("web_fetch_pages", True)),
            )
            self.source_urls = source_urls(payload)
            self.effective_query = query
            return web_search_context_text(payload)

        raise RuntimeError(f"Unsupported scheduled task type: {task_type}")

    @Slot()
    def run(self):
        task_id = self.task.get("id", "")
        try:
            prompt = str(self.task.get("prompt", "")).strip()
            model = str(self.task.get("model", "")).strip()
            task_type = str(self.task.get("task_type", "weather")).strip().lower()

            if not prompt:
                raise RuntimeError("Scheduled task prompt is empty.")
            if not model:
                raise RuntimeError("Scheduled task model is not set.")

            tool_context = self._build_context(model)

            if tool_context:
                user_content = (
                    f"SCHEDULED TASK TYPE: {task_type}\n"
                    f"SCHEDULED TASK:\n{prompt}\n\n"
                    f"AUTHORIZED TOOL DATA:\n{tool_context}"
                )
                system_content = (
                    "You are running a scheduled local-assistant task. "
                    "For current or external facts, use ONLY the AUTHORIZED TOOL DATA "
                    "in the user message. Do not use memory or prior knowledge to fill "
                    "missing facts. If the supplied sources are irrelevant or do not "
                    "support the requested topic, explicitly say that no relevant "
                    "sources were found instead of answering a different topic. "
                    "Never invent scores, ratings, prices, specifications, dates, "
                    "comparisons, or recommendations. Keep the answer concise unless "
                    "the task asks for detail."
                )
            else:
                user_content = (
                    f"SCHEDULED TASK TYPE: custom\n"
                    f"SCHEDULED TASK:\n{prompt}"
                )
                system_content = (
                    "You are running a scheduled local-assistant task. "
                    "No live external data source is attached to this task. "
                    "Do not claim that you checked current internet data."
                )

            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ]

            content = self.client.chat_once(
                model=model,
                messages=messages,
            )
            if not content.strip():
                raise RuntimeError("The model returned an empty scheduled result.")

            final_content = content.strip()
            if self.source_urls:
                source_lines = "\n".join(
                    f"- {url}" for url in self.source_urls[:10]
                )
                final_content += (
                    "\n\n---\n"
                    f"Search query: {self.effective_query}\n"
                    "Sources:\n"
                    f"{source_lines}"
                )

            self.finished.emit(task_id, final_content)
        except Exception as exc:
            self.failed.emit(task_id, str(exc))