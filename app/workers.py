import re
import threading
import unicodedata

from PySide6.QtCore import QObject, Signal, Slot

from .artifact_service import ArtifactPlanItem, create_artifact
from .document_tools import (
    build_document_messages,
    build_excel_messages,
    build_summary_messages,
)
from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .crypto_market_data import run_crypto_market_request
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
from .multi_asset_market_data import run_multi_asset_market_request
from .language_policy import (
    detect_user_language,
    response_language_instruction,
    response_language_matches,
)
from .ollama_client import OllamaClient
from .response_guard import guard_response
from .runtime_control import ExecutionControl
from .scheduled_task_executor import ScheduledTaskExecutor
from .weather_tool import get_weather, weather_context_text
from .web_intent import answer_requires_web_fallback
from .web_research_pipeline import WebResearchPipeline
from .web_search_tool import (
    authoritative_current_fact,
    build_search_plan,
    select_authoritative_current_fact,
    is_current_version_query,
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


class MarketDataWorker(QObject):
    token = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        messages: list[dict],
        user_prompt: str,
        extension: dict,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.extension = dict(extension or {})
        self._stop_event = threading.Event()
        self.used_web_fallback = False

    @Slot()
    def run(self):
        try:
            if self._stop_event.is_set():
                self.finished.emit()
                return

            try:
                answer = run_crypto_market_request(
                    self.extension,
                    self.user_prompt,
                ).strip()
            except Exception:
                self.used_web_fallback = True
                answer = run_market_web_request(
                    self.client,
                    self.model,
                    self.messages,
                    self.user_prompt,
                ).strip()

            if self._stop_event.is_set():
                self.finished.emit()
                return

            if not answer:
                raise RuntimeError("Crypto market data returned an empty answer.")

            self.token.emit(answer)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()


class MultiAssetMarketDataWorker(QObject):
    token = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        messages: list[dict],
        user_prompt: str,
        extension: dict,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.extension = dict(extension or {})
        self._stop_event = threading.Event()
        self.used_web_fallback = False

    @Slot()
    def run(self):
        try:
            if self._stop_event.is_set():
                self.finished.emit()
                return

            try:
                answer = run_multi_asset_market_request(
                    self.extension,
                    self.user_prompt,
                ).strip()
            except Exception:
                self.used_web_fallback = True
                answer = run_market_web_request(
                    self.client,
                    self.model,
                    self.messages,
                    self.user_prompt,
                ).strip()

            if self._stop_event.is_set():
                self.finished.emit()
                return

            if not answer:
                raise RuntimeError("Multi-asset market data returned an empty answer.")

            self.token.emit(answer)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()


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
        *,
        compact_market_quote: bool = False,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.compact_market_quote = bool(compact_market_quote)
        self._stop_event = threading.Event()
        self.web_research_pipeline = WebResearchPipeline(self)
        self._latest_evidence_ledgers = []

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

    def _generate_search_queries_legacy(self):
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

    def _generate_search_queries(self):
        return self.web_research_pipeline.generate_search_queries(
            self._generate_search_queries_legacy
        )


    def _authoritative_fact_answer(self, fact):
        value = str(fact.get("value", "")).strip()
        title = str(fact.get("title", "")).strip() or "Official source"
        url = str(fact.get("url", "")).strip()
        source = f"[{title}]({url})" if url else title

        instruction = self._conversation_language_instruction()
        if "Hungarian" in instruction:
            return (
                f"A hivatalos elsődleges forrás alapján a legfrissebb verzió: "
                f"**{value}**. Forrás: {source}"
            )
        if "German" in instruction:
            return (
                f"Laut der offiziellen Primärquelle ist die neueste Version "
                f"**{value}**. Quelle: {source}"
            )
        return (
            f"According to the official first-party source, the latest version is "
            f"**{value}**. Source: {source}"
        )

    def _canonical_authoritative_fact(self, facts):
        return select_authoritative_current_fact(
            self.user_prompt,
            facts,
        )

    def _enforce_authoritative_facts(self, answer, facts):
        final = str(answer or "").strip()
        fact = self._canonical_authoritative_fact(facts)
        if not fact:
            return final

        value = str(fact.get("value", "")).strip()
        if value and value not in final:
            return self._authoritative_fact_answer(fact)
        return final


    @staticmethod
    def _version_like_tokens(text):
        return set(
            re.findall(
                r"(?i)(?:\bv?\d+(?:\.\d+){1,3}(?:[-+][0-9a-z.-]+)?\b|"
                r"\b[a-z][a-z0-9_-]*\d+(?:\.\d+){1,3}\b)",
                str(text or ""),
            )
        )

    def _compact_current_version_answer(self, answer, authoritative_facts):
        """
        Keep simple latest/current version answers direct.

        The full search/source appendix is emitted separately by the host, so the
        visible answer should not become a research report unless the user asked
        for one. Authoritative exact facts remain deterministic. Otherwise a
        bounded rewrite may shorten the already-grounded answer, but it may not
        introduce new version-like tokens.
        """
        final = str(answer or "").strip()
        if not is_current_version_query(self.user_prompt):
            return final

        fact = self._canonical_authoritative_fact(authoritative_facts)
        if fact:
            return self._authoritative_fact_answer(fact)

        if len(final) <= 700:
            return final

        compact = self.client.chat_once(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the supplied grounded answer into at most three short "
                        "sentences. Answer the user's latest/current version question "
                        "immediately. Preserve product/model/version names and URLs exactly. "
                        "Do not add, infer, correct, rank, or remove the core answer. "
                        "Do not include timelines, key-highlights sections, ecosystem "
                        "summaries, API change lists, or research-process narration. "
                        + self._conversation_language_instruction()
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"USER QUESTION:\n{self.user_prompt}\n\n"
                        f"GROUNDED ANSWER TO SHORTEN:\n{final}"
                    ),
                },
            ],
        ).strip()

        if not compact or len(compact) > 900:
            return final
        if not response_language_matches(self.user_prompt, compact):
            return final
        if not self._version_like_tokens(compact).issubset(
            self._version_like_tokens(final)
        ):
            return final
        return compact


    def _wants_detailed_web_answer(self):
        normalized = self._fold_text(self.user_prompt)
        detail_markers = (
            "részletes",
            "reszletes",
            "részletesen",
            "reszletesen",
            "magyarázd el",
            "magyarazd el",
            "elemezd",
            "elemzés",
            "elemzes",
            "összefoglaló",
            "osszefoglalo",
            "riport",
            "report",
            "detailed",
            "in detail",
            "explain",
            "analysis",
            "analyze",
            "compare",
            "comparison",
            "list all",
            "vollständig",
            "vollstaendig",
            "ausführlich",
            "ausfuhrlich",
            "erkläre",
            "erklaere",
            "analyse",
            "bericht",
        )
        return any(marker in normalized for marker in detail_markers)

    @staticmethod
    def _numeric_fact_tokens(text):
        return set(
            re.findall(
                r"(?i)(?:[$€£]\s*)?\b\d[\d\s.,]*"
                r"(?:\s*(?:usd|eur|gbp|huf|btc|eth|%|tb|gb|mb|mhz|mt/s))?\b",
                str(text or ""),
            )
        )

    @staticmethod
    def _url_tokens(text):
        return set(
            re.findall(r"https?://[^\s)\]>]+", str(text or ""))
        )

    def _compact_grounded_answer(self, answer):
        """
        Apply one interface-wide answer-shaping rule to ordinary grounded web
        answers: answer the user's actual question first, briefly, while leaving
        the host's search/source appendix available underneath.

        Detailed/report/explanation requests opt out. The rewrite is bounded:
        it may omit supporting detail, but it may not introduce new numeric facts
        or URLs that were not already present in the grounded answer.
        """
        original = str(answer or "")
        final = original.strip()
        if not final:
            return final
        if self._wants_detailed_web_answer():
            return original

        if len(final) <= 650:
            return final

        compact = self.client.chat_once(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the supplied grounded web answer into a concise primary "
                        "answer. Answer the user's exact question immediately in the first "
                        "sentence, then add at most two short supporting sentences if useful. "
                        "Prefer the concrete requested value/result over advice about where "
                        "to look. Do not add new facts, numbers, prices, dates, percentages, "
                        "versions, URLs, recommendations, or caveats. You may omit secondary "
                        "details because the host app shows the search/source appendix "
                        "separately. Preserve uncertainty or delayed-data caveats when they "
                        "materially qualify the requested value. "
                        + self._conversation_language_instruction()
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"USER QUESTION:\n{self.user_prompt}\n\n"
                        f"GROUNDED ANSWER TO SHORTEN:\n{final}"
                    ),
                },
            ],
        ).strip()

        if not compact or len(compact) > 750:
            return final
        if not response_language_matches(self.user_prompt, compact):
            return final
        if not self._numeric_fact_tokens(compact).issubset(
            self._numeric_fact_tokens(final)
        ):
            return final
        if not self._url_tokens(compact).issubset(self._url_tokens(final)):
            return final
        return compact


    def _compact_market_quote_answer(self, answer):
        original = str(answer or "").strip()
        if not self.compact_market_quote or not original:
            return original

        compact = self.client.chat_once(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite the supplied grounded market answer into one short "
                        "sentence, or at most two short sentences if a material delayed-"
                        "data or market-state caveat is required. Put the requested current "
                        "price or exchange rate in the first sentence. Do not include "
                        "analysis, outlook, investment commentary, bullet lists, search "
                        "queries, search providers, source inventories, or offers to do "
                        "more work. Do not add or change any number, price, percentage, "
                        "currency, ticker, date, URL, or factual claim. "
                        + self._conversation_language_instruction()
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"USER QUESTION:\n{self.user_prompt}\n\n"
                        f"GROUNDED MARKET ANSWER:\n{original}"
                    ),
                },
            ],
        ).strip()

        if not compact or len(compact) > 360:
            return original
        if not response_language_matches(self.user_prompt, compact):
            return original
        if not self._numeric_fact_tokens(compact).issubset(
            self._numeric_fact_tokens(original)
        ):
            return original
        if not self._url_tokens(compact).issubset(self._url_tokens(original)):
            return original
        return compact


    def _safe_evidence_failure_base(self, answer_rejected=False):
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

    def _safe_evidence_failure(self, answer_rejected=False):
        return self.web_research_pipeline.safe_evidence_failure(
            answer_rejected=answer_rejected,
            ledgers=self._latest_evidence_ledgers,
            legacy_failure=self._safe_evidence_failure_base,
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
            authoritative_facts = []

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

                fact = authoritative_current_fact(payload)
                if fact and not any(
                    existing.get("kind") == fact.get("kind")
                    and existing.get("value") == fact.get("value")
                    and existing.get("url") == fact.get("url")
                    for existing in authoritative_facts
                ):
                    authoritative_facts.append(fact)

                context_body = web_search_context_text(payload)
                if isinstance(payload.get("search_plan"), dict):
                    verified_results, ledgers, constrained = filter_verified_results(
                        query,
                        payload.get("results") or [],
                    )
                    self._latest_evidence_ledgers = list(ledgers or [])
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
                    "in the same bullet or sentence using Markdown link syntax. "
                    "When a result has a Scope note saying it is a qualified subproduct/tool "
                    "not named in the query, do not use that result as the current-version "
                    "authority for the broader product or model family. "
                    "When AUTHORITATIVE CURRENT FACT data is present, preserve its exact "
                    "value for the requested latest/current fact and prefer that first-party "
                    "authority over conflicting secondary sources or model priors. "
                    "For ordinary factual web questions, answer the user's exact question "
                    "immediately and keep the primary answer concise: normally one to three "
                    "short sentences. Do not replace a requested value with advice about where "
                    "to look when the authorized evidence already contains that value. "
                    "Only provide a long explanation, report, analysis, comparison, or list "
                    "when the user explicitly asks for that level of detail. Do not produce "
                    "timelines, key-highlights sections, ecosystem summaries, API change lists, "
                    "or research-process narration by default; the host appends the search/source "
                    "appendix separately. For a simple latest/current version question, preserve "
                    "the direct authoritative answer. Do not say you cannot browse "
                    "the web; the authorized web data has already "
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
            answer = self._enforce_authoritative_facts(
                answer,
                authoritative_facts,
            )
            answer = self._compact_current_version_answer(
                answer,
                authoritative_facts,
            )
            answer = self._compact_grounded_answer(answer)
            answer = self._compact_market_quote_answer(answer)

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
                    if self.web_research_pipeline.deterministic_verified_answer(
                        evidence_ledgers
                    ):
                        verification_status = (
                            "Evidence verification: PASS "
                            "(host-verified fallback used)"
                        )
                    else:
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

            if not self.compact_market_quote:
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


def _run_web_worker(worker):
    chunks = []
    errors = []
    worker.token.connect(chunks.append)
    worker.failed.connect(errors.append)
    worker.run()

    if errors:
        raise RuntimeError(errors[0])

    answer = "".join(chunks).strip()
    if not answer:
        raise RuntimeError("Web research returned an empty answer.")
    return answer


def run_chat_web_request(client, model, messages, user_prompt):
    """Run the existing grounded web worker synchronously and collect its answer."""
    return _run_web_worker(
        ChatWebWorker(
            client,
            model,
            messages,
            user_prompt,
        )
    )


def run_market_web_request(client, model, messages, user_prompt):
    """Run concise grounded web fallback for a live market-value lookup."""
    return _run_web_worker(
        ChatWebWorker(
            client,
            model,
            messages,
            user_prompt,
            compact_market_quote=True,
        )
    )


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
        *,
        allow_web_fallback: bool = True,
        constraints=None,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.allow_web_fallback = bool(allow_web_fallback)
        self.constraints = constraints
        self._stop_event = threading.Event()
        self.execution_control = ExecutionControl()
        self.used_web_fallback = False

    @Slot()
    def run(self):
        try:
            if self._stop_event.is_set():
                self.finished.emit()
                return

            if isinstance(self.client, OllamaClient):
                draft_parts = []
                self.client.chat_stream(
                    model=self.model,
                    messages=self.messages,
                    on_token=draft_parts.append,
                    should_stop=self._stop_event.is_set,
                    control=self.execution_control,
                )
                draft = "".join(draft_parts).strip()
            else:
                draft = self.client.chat_once(
                    model=self.model,
                    messages=self.messages,
                ).strip()

            if (
                self.allow_web_fallback
                and not self._stop_event.is_set()
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

            if self.constraints is not None:
                final = guard_response(
                    self.client,
                    self.model,
                    self.user_prompt,
                    final,
                    constraints=self.constraints,
                    control=self.execution_control,
                )

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
        self.execution_control.cancellation.cancel()


def _grounded_artifact_version_tokens(text):
    return set(
        re.findall(
            r"(?i)(?:\bv?\d+(?:\.\d+){1,3}(?:[-+][0-9a-z.-]+)?\b|"
            r"\b[a-z][a-z0-9_-]*\d+(?:\.\d+){1,3}\b)",
            str(text or ""),
        )
    )


def _grounded_artifact_url_tokens(text):
    return set(
        re.findall(r"https?://[^\s)\]>]+", str(text or ""))
    )


def _grounded_artifact_risk_tokens(text):
    value = str(text or "")
    patterns = (
        r"(?<!\w)[$€£]\s*\d+(?:[.,]\d+)?(?:\s*(?:usd|eur|gbp|huf))?",
        r"\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp|huf|btc|eth|%)\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{4}/\d{2}/\d{2}\b",
        r"\b(?:19|20)\d{2}\b",
    )
    tokens = set()
    for pattern in patterns:
        tokens.update(re.findall(pattern, value, flags=re.IGNORECASE))
    return tokens


def grounded_artifact_unsupported_tokens(content, authority_text):
    """
    Return factual literals introduced by generated artifact content that are
    absent from the user request + verified grounded source context.
    """
    content = str(content or "")
    authority_text = str(authority_text or "")

    unsupported = set()
    unsupported.update(
        _grounded_artifact_version_tokens(content)
        - _grounded_artifact_version_tokens(authority_text)
    )
    unsupported.update(
        _grounded_artifact_url_tokens(content)
        - _grounded_artifact_url_tokens(authority_text)
    )
    unsupported.update(
        _grounded_artifact_risk_tokens(content)
        - _grounded_artifact_risk_tokens(authority_text)
    )
    return tuple(sorted(unsupported, key=str.casefold))


class ArtifactActionWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        messages: list[dict],
        user_prompt: str,
        artifact_plans,
        *,
        use_web=False,
        constraints=None,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.artifact_plans = tuple(artifact_plans or ())
        self.use_web = bool(use_web)
        self.constraints = constraints
        self._stop_event = threading.Event()
        self.execution_control = ExecutionControl(
            budget=__import__("app.runtime_control", fromlist=["ExecutionBudget"]).ExecutionBudget(
                timeout_seconds=300.0,
                max_model_calls=max(4, len(self.artifact_plans) * 3),
            )
        )

    def _artifact_messages(self, plan, source_context=""):
        if not isinstance(plan, ArtifactPlanItem):
            raise TypeError(
                "artifact_plans must contain ArtifactPlanItem values"
            )

        prompt = str(plan.prompt or self.user_prompt).strip()
        if source_context:
            prompt = (
                prompt
                + "\n\nVERIFIED WEB RESEARCH SOURCE:\n"
                + source_context
                + "\n\nGROUNDING CONTRACT:\n"
                + "Use the verified source above as the factual authority. "
                + "Do not introduce any version number, date, year, price, "
                + "percentage, currency amount, URL, or other numeric factual "
                + "literal that is not explicitly present in the verified "
                + "source or the user request. If a requested fact is absent, "
                + "state that it is unknown from the verified source. "
                + "Do not fill gaps from model memory."
            )

        fmt = plan.request.format
        if fmt == "xlsx":
            return build_excel_messages(prompt)
        if fmt == "summary":
            return build_summary_messages(prompt)
        return build_document_messages(prompt)

    @Slot()
    def run(self):
        try:
            if not self.artifact_plans:
                raise RuntimeError("Artifact action contains no artifact plan.")

            source_context = ""
            if self.use_web:
                source_context = run_chat_web_request(
                    self.client,
                    self.model,
                    self.messages,
                    self.user_prompt,
                ).strip()

            results = []
            for plan in self.artifact_plans:
                if self._stop_event.is_set():
                    break

                if isinstance(self.client, OllamaClient):
                    content = self.client.chat_once(
                        model=self.model,
                        messages=self._artifact_messages(
                            plan,
                            source_context=source_context,
                        ),
                        control=self.execution_control,
                    ).strip()
                else:
                    content = self.client.chat_once(
                        model=self.model,
                        messages=self._artifact_messages(
                            plan,
                            source_context=source_context,
                        ),
                    ).strip()
                if not content:
                    raise RuntimeError(
                        "The model returned empty artifact content."
                    )

                if source_context:
                    authority_text = (
                        self.user_prompt
                        + "\n"
                        + str(plan.prompt or "")
                        + "\n"
                        + source_context
                    )
                    unsupported = grounded_artifact_unsupported_tokens(
                        content,
                        authority_text,
                    )
                    if unsupported:
                        repair_messages = self._artifact_messages(
                            plan,
                            source_context=source_context,
                        )
                        repair_messages = list(repair_messages) + [
                            {
                                "role": "system",
                                "content": (
                                    "The previous draft was rejected because it "
                                    "introduced unsupported factual literals: "
                                    + ", ".join(unsupported)
                                    + ". Regenerate the artifact content from "
                                    "the verified source only. Preserve supported "
                                    "facts exactly and omit unsupported literals."
                                ),
                            }
                        ]
                        if isinstance(self.client, OllamaClient):
                            content = self.client.chat_once(
                                model=self.model,
                                messages=repair_messages,
                                control=self.execution_control,
                            ).strip()
                        else:
                            content = self.client.chat_once(
                                model=self.model,
                                messages=repair_messages,
                            ).strip()
                        if not content:
                            raise RuntimeError(
                                "The grounded artifact repair returned empty content."
                            )

                        unsupported = grounded_artifact_unsupported_tokens(
                            content,
                            authority_text,
                        )
                        if unsupported:
                            raise RuntimeError(
                                "Grounded artifact rejected unsupported factual "
                                "literals: " + ", ".join(unsupported)
                            )

                if self.constraints is not None:
                    content = guard_response(
                        self.client,
                        self.model,
                        str(plan.prompt or self.user_prompt),
                        content,
                        constraints=self.constraints,
                        control=self.execution_control,
                    )

                path = create_artifact(
                    plan.request.format,
                    content=content,
                    title=self.user_prompt[:96] or "Local AI Document",
                    preset=plan.request.preset,
                    source_text=(
                        self.user_prompt
                        + (
                            "\n\nVERIFIED WEB RESEARCH SOURCE:\n"
                            + source_context
                            if source_context
                            else ""
                        )
                    ),
                    model_name=self.model,
                )
                results.append({
                    "path": str(path),
                    "format": plan.request.format,
                    "preset": plan.request.preset,
                })

            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()
        self.execution_control.cancellation.cancel()


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
        executor = ScheduledTaskExecutor(self.client)
        return executor._generate_search_query(prompt, model)

    def _executor(self):
        # Inject the module-level tool functions so existing worker tests and
        # runtime monkeypatches continue to exercise the same authorities.
        return ScheduledTaskExecutor(
            self.client,
            query_generator=self._generate_search_query,
            get_weather_fn=get_weather,
            weather_context_text_fn=weather_context_text,
            search_ebay_fn=search_ebay,
            ebay_context_text_fn=ebay_context_text,
            get_computer_status_fn=get_computer_status,
            computer_status_context_text_fn=computer_status_context_text,
            search_web_fn=search_web,
            web_search_context_text_fn=web_search_context_text,
            source_urls_fn=source_urls,
        )

    @Slot()
    def run(self):
        task_id = self.task.get("id", "")
        try:
            result = self._executor().execute(self.task)
            self.source_urls = list(result.source_urls)
            self.effective_query = result.effective_query
            self.finished.emit(task_id, result.content)
        except Exception as exc:
            self.failed.emit(task_id, str(exc))
        finally:
            release = getattr(self.client, "release_owned_models", None)
            if callable(release):
                try:
                    release(timeout=5.0)
                except Exception:
                    pass
