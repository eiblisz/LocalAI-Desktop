import hashlib
import re
import threading
import unicodedata
from time import perf_counter

from PySide6.QtCore import QObject, Signal, Slot

from .artifact_service import ArtifactPlanItem, create_artifact
from .brave_llm_context import context_mode as brave_context_mode
from .document_tools import (
    build_document_messages,
    build_excel_messages,
    build_summary_messages,
)
from .context_guard import guard_context_response
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
from .followup_resolution import resolve_contextual_followup
from .current_turn_binding import guard_current_turn_binding
from .direct_fact import (
    derive_premise_neutral_query,
    deterministic_hungarian_fact_fallback,
    requested_fact_supported,
    targeted_fact_refinement_query,
)
from .grounded_factual_guard import guard_grounded_answer
from .generation_policy import (
    SYNTHESIS_HYBRID,
    SYNTHESIS_LOCAL,
    SYNTHESIS_WEB,
    build_generation_policy,
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
    effective_response_language,
    response_language_instruction,
    response_language_matches,
)
from .ollama_client import OllamaClient, ollama_failure_metadata
from .response_guard import ResponseValidationError, guard_response
from .request_semantics import (
    TASK_DIRECT_FACT,
    TASK_ENTITY_OVERVIEW,
    classify_request,
    request_profile_instruction,
)
from .search_query_validation import validate_search_queries, validate_search_query
from .runtime_control import ExecutionBudget, ExecutionControl
from .scheduled_task_executor import ScheduledTaskExecutor
from .weather_tool import get_weather, weather_context_text
from .web_intent import answer_requires_web_fallback, is_factual_risk_request
from .web_evidence import compact_evidence_authority, compact_evidence_bundle
from .web_research_pipeline import WebResearchPipeline
from .web_search_tool import (
    authoritative_current_fact,
    build_search_plan,
    select_authoritative_current_fact,
    is_current_version_query,
    fetch_result_pages,
    search_web,
    source_entries,
    source_urls,
    web_search_context_text,
)


def _record_ollama_timing(trace, metadata, wall_ms):
    """Attach optional native Ollama timing without assuming a specific model."""
    if trace is None or not isinstance(metadata, dict):
        return

    def milliseconds(name):
        try:
            return max(0.0, float(metadata.get(name) or 0.0) / 1_000_000.0)
        except (TypeError, ValueError):
            return 0.0

    load_ms = milliseconds("load_duration")
    prompt_ms = milliseconds("prompt_eval_duration")
    generation_ms = milliseconds("eval_duration")
    total_ms = milliseconds("total_duration")
    native_runtime_ms = total_ms or (load_ms + prompt_ms + generation_ms)
    trace.mark_duration("ollama_load", load_ms)
    trace.mark_duration("ollama_prompt_evaluation", prompt_ms)
    trace.mark_duration("ollama_generation", generation_ms)
    trace.mark_duration(
        "ollama_queue_or_transport",
        max(0.0, float(wall_ms or 0.0) - native_runtime_ms),
    )
    trace.add_metadata(
        ollama_native_total_ms=round(total_ms, 2),
        ollama_prompt_eval_count=metadata.get("prompt_eval_count"),
        ollama_generated_count=metadata.get("eval_count"),
    )


def _record_ollama_failure(trace, exc):
    """Preserve a classified root cause before the UI presents a safe error."""
    if trace is not None:
        metadata = ollama_failure_metadata(exc)
        trace.add_metadata(**metadata)
        call_phase = metadata.get("ollama_call_phase")
        if call_phase == "primary_generation":
            trace.end("primary_generation", primary_generation_result="failed")
        elif call_phase == "hungarian_fluency_audit":
            trace.end("hungarian_fluency_audit", hungarian_fluency_audit_result="failed")
        elif call_phase == "language_repair":
            trace.end("language_repair", language_repair_result="failed")


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


class ResponseMemoryWorker(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        client,
        model,
        response_text,
        memory_store,
        source_chat_id,
        source_message_id,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.response_text = str(response_text or "").strip()
        self.memory_store = memory_store
        self.source_chat_id = str(source_chat_id or "").strip()
        self.source_message_id = str(source_message_id or "").strip()
        self.saved_count = 0

    @Slot()
    def run(self):
        try:
            from .memory_runtime import remember_response

            written = remember_response(
                self.client,
                self.model,
                self.response_text,
                self.memory_store,
                source_chat_id=self.source_chat_id or None,
                source_message_id=self.source_message_id or None,
            )
            self.saved_count = len(written)
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self):
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
    phase = Signal(str)
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
        trace=None,
        explicit_batch_child=False,
        output_budget=None,
        synthesis_route=None,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.original_user_prompt = str(user_prompt or "").strip()
        self.followup_resolution = resolve_contextual_followup(
            self.original_user_prompt,
            self.messages,
            explicit_batch_child=explicit_batch_child,
        )
        self.user_prompt = (
            self.followup_resolution.resolved_intent
            or self.original_user_prompt
        )
        classification_started = perf_counter()
        self.request_profile = classify_request(self.user_prompt)
        default_generation_policy = build_generation_policy(
            self.user_prompt,
            profile=self.request_profile,
            use_web=True,
        )
        self.synthesis_route = str(
            synthesis_route or SYNTHESIS_WEB
        ).upper()
        if self.synthesis_route not in {
            SYNTHESIS_LOCAL,
            SYNTHESIS_WEB,
            SYNTHESIS_HYBRID,
        }:
            self.synthesis_route = SYNTHESIS_WEB
        self.output_budget = max(
            1,
            int(output_budget or default_generation_policy.output_budget),
        )
        self.response_length = default_generation_policy.response_length
        self._classification_ms = round(
            (perf_counter() - classification_started) * 1000,
            2,
        )
        self.execution_control = ExecutionControl.for_request_profile(
            self.request_profile
        )
        self.compact_market_quote = bool(compact_market_quote)
        self.trace = trace
        if self.trace is not None:
            self.trace.add_metadata(
                child_profile=self.request_profile.kind,
                child_requested_fact=self.request_profile.requested_fact,
                child_relation=self.request_profile.relation,
                semantic_confidence=self.request_profile.semantic_confidence,
                freshness=self.request_profile.freshness,
                synthesis_route=self.synthesis_route,
                response_length=self.response_length,
                output_budget=self.output_budget,
                web_required=True,
            )
        self._stop_event = threading.Event()
        self.web_research_pipeline = WebResearchPipeline(self)
        self._latest_evidence_ledgers = []
        self.query_validation = {"status": "not_run", "rejections": []}
        self.source_metadata = []
        self.diagnostic_metadata = {}
        self._factual_authority_text = ""
        self._direct_query_strategy = "not_applicable"

    def _set_diagnostics(
        self,
        *,
        queries=(),
        providers=(),
        provider_fallbacks=(),
        evidence_ledger_count=0,
        context_modes=(),
        verification_status="",
        evidence_diagnostic="",
        evidence_coverage="not_applicable",
    ):
        self.diagnostic_metadata = {
            "route": "web",
            "synthesis_route": self.synthesis_route,
            "search_queries": list(queries),
            "providers": list(providers),
            "provider_fallbacks": list(provider_fallbacks),
            "query_validation": dict(self.query_validation),
            "evidence_ledger_count": int(evidence_ledger_count or 0),
            "context_modes": list(context_modes),
            "verification_status": str(verification_status or ""),
            "evidence_diagnostic": str(evidence_diagnostic or ""),
            "evidence_coverage": str(evidence_coverage or "not_applicable"),
            "request_kind": self.request_profile.kind,
            "requested_fact": self.request_profile.requested_fact,
            "relation": self.request_profile.relation,
            "semantic_confidence": self.request_profile.semantic_confidence,
            "freshness": self.request_profile.freshness,
            "response_depth": self.request_profile.response_depth,
            "response_length": self.response_length,
            "output_budget": self.output_budget,
            "research_breadth": self.request_profile.research_breadth,
            "query_budget": self.request_profile.query_budget,
            "source_budget": self.request_profile.source_budget,
            "page_fetch_budget": self.request_profile.page_fetch_budget,
            "model_call_count": self.execution_control.budget.model_calls,
            "search_count": self.execution_control.budget.search_calls,
            "page_fetch_count": self.execution_control.budget.page_fetches,
            "repair_count": self.execution_control.budget.repairs,
        }

    def _chat_once(self, **kwargs):
        if isinstance(self.client, OllamaClient):
            return self.client.chat_once(
                control=self.execution_control,
                **kwargs,
            )
        self.execution_control.claim_model_call()
        while True:
            try:
                return self.client.chat_once(**kwargs)
            except TypeError as exc:
                unsupported = next(
                    (
                        name for name in ("num_predict", "call_phase")
                        if name in str(exc) and name in kwargs
                    ),
                    "",
                )
                if not unsupported:
                    raise
                kwargs.pop(unsupported)

    def _chat_stream(self, **kwargs):
        if isinstance(self.client, OllamaClient):
            return self.client.chat_stream(
                control=self.execution_control,
                **kwargs,
            )
        self.execution_control.claim_model_call()
        while True:
            try:
                return self.client.chat_stream(**kwargs)
            except TypeError as exc:
                unsupported = next(
                    (
                        name for name in ("num_predict", "call_phase")
                        if name in str(exc) and name in kwargs
                    ),
                    "",
                )
                if not unsupported:
                    raise
                kwargs.pop(unsupported)

    def _search_payload(self, query, *, max_results, fetch_pages):
        self.execution_control.claim_search()
        timeout = self.execution_control.request_timeout(20.0)
        try:
            return search_web(
                query,
                max_results=max_results,
                fetch_pages=fetch_pages,
                timeout=timeout,
            )
        except TypeError as exc:
            # Older in-repo test doubles and third-party adapters may retain
            # the legacy three-argument callable contract.
            if "timeout" not in str(exc):
                raise
            return search_web(
                query,
                max_results=max_results,
                fetch_pages=fetch_pages,
            )

    def _fetch_direct_fact_page(self, payload):
        self.execution_control.claim_page_fetch()
        return fetch_result_pages(
            payload,
            page_fetch_budget=1,
            timeout=self.execution_control.request_timeout(8.0),
        )

    @staticmethod
    def _merge_direct_fact_payloads(primary, refinement):
        """Keep premise and requested-fact evidence together after one refinement."""
        merged = dict(primary or {})
        merged["results"] = [
            *list((primary or {}).get("results") or []),
            *list((refinement or {}).get("results") or []),
        ]
        primary_timing = dict((primary or {}).get("timing") or {})
        refinement_timing = dict((refinement or {}).get("timing") or {})
        for key in ("provider_ms", "page_fetch_ms", "total_search_ms"):
            primary_timing[key] = round(
                float(primary_timing.get(key, 0.0) or 0.0)
                + float(refinement_timing.get(key, 0.0) or 0.0),
                2,
            )
        primary_timing["page_fetch_count"] = int(
            primary_timing.get("page_fetch_count", 0) or 0
        ) + int(refinement_timing.get("page_fetch_count", 0) or 0)
        merged["timing"] = primary_timing
        merged["provider_chain_errors"] = list(dict.fromkeys([
            *list((primary or {}).get("provider_chain_errors") or []),
            *list((refinement or {}).get("provider_chain_errors") or []),
        ]))
        return merged

    def _followup_clarification(self):
        return self.followup_resolution.clarification

    def _invalid_query_clarification(self):
        if "Hungarian" in self._conversation_language_instruction():
            return (
                "Nem indítok webes keresést, mert a kérésből nem lett "
                "biztonságos, értelmes keresőkifejezés. Kérlek, írd le "
                "röviden, mit szeretnél megtudni."
            )
        return (
            "I did not start a web search because this request did not produce "
            "a safe, meaningful search query. Please add a little more context."
        )

    def _validated_search_queries(self, candidates):
        validation_intent = (
            self._search_constraint_authority()
            if self._is_research_followup()
            else self.user_prompt
        )
        accepted, rejected = validate_search_queries(candidates, validation_intent)

        if (
            is_factual_risk_request(self.user_prompt)
            and self._direct_query_strategy not in {
                "premise_neutral_title_relation",
                "identity_lookup_subject",
            }
        ):
            direct = validate_search_query(self.user_prompt, validation_intent)
            if direct.accepted:
                direct_folded = self._fold_text(direct.query)
                accepted = [
                    direct.query,
                    *[
                        query for query in accepted
                        if self._fold_text(query) != direct_folded
                    ],
                ][:4]

        if accepted:
            self.query_validation = {
                "status": "accepted",
                "rejections": rejected,
            }
            query_limit = (
                4
                if self._has_multiple_research_topics()
                else self.request_profile.query_budget
            )
            return accepted[:query_limit]

        repair = validate_search_query(
            self._search_constraint_authority(),
            validation_intent,
        )
        if repair.accepted:
            self.query_validation = {
                "status": "bounded_repair",
                "rejections": rejected,
            }
            return [repair.query]

        self.query_validation = {
            "status": "rejected",
            "rejections": rejected + [repair.reason],
        }
        return []

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
        from .text_normalization import canonical_match_text
        return canonical_match_text(value)

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

    def _response_language_source(self):
        if detect_user_language(self.original_user_prompt) != "unknown":
            return self.original_user_prompt

        if self.followup_resolution.status == "resolved":
            for message in reversed(self.messages):
                if message.get("role") != "user":
                    continue
                text = " ".join(str(message.get("content") or "").split())
                if not text or text == self.original_user_prompt:
                    continue
                if detect_user_language(text) != "unknown":
                    return text

        return self.original_user_prompt or self.user_prompt

    def _conversation_language_instruction(self):
        return response_language_instruction(self._response_language_source())

    def _repair_response_language(self, answer):
        language_source = self._response_language_source()
        try:
            return guard_response(
                self.client,
                self.model,
                language_source,
                answer,
                control=self.execution_control,
                output_budget=self.output_budget,
                trace=self.trace,
                phase_callback=self.phase.emit,
            )
        except ResponseValidationError as exc:
            if self.trace is not None:
                self.trace.add_metadata(
                    language_repair_failure_classification=str(
                        getattr(exc, "localai_failure_classification", "")
                    ),
                )
            if effective_response_language(language_source) == "hu":
                fallback = deterministic_hungarian_fact_fallback(
                    self._factual_authority_text,
                    self.request_profile.requested_fact,
                )
                if fallback:
                    return fallback
            raise

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

        raw = self._chat_once(
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

        compact = self._chat_once(
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
        return (
            self.request_profile.response_depth != "concise"
            or self.response_length == "long"
        )

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

        compact = self._chat_once(
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

        compact = self._chat_once(
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

    def _safe_no_public_sources(self):
        if self.request_profile.response_language == "hu":
            return (
                "Most nem találtam elég megbízható nyilvános forrást a válaszhoz. "
                "Próbáld meg később vagy pontosabb kulcsszavakkal."
            )
        return (
            "I could not find enough reliable public sources for this answer. "
            "Please try again later or use more specific keywords."
        )

    def _hybrid_without_usable_sources(self):
        """Keep stable explanatory synthesis useful when its web add-on fails."""
        answer_parts = []
        self.phase.emit(f"{self.model} válaszol")
        self._chat_stream(
            model=self.model,
            num_predict=self.output_budget,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer the stable explanatory parts of the user's request "
                        "from general knowledge. The requested fresh/external evidence "
                        "could not be verified, so do not invent or state current dates, "
                        "numbers, prices, versions, URLs, or events. Say briefly that "
                        "the fresh add-on could not be verified, then give the useful "
                        "stable explanation. "
                        + self._conversation_language_instruction()
                    ),
                },
                {"role": "user", "content": self.user_prompt},
            ],
            on_token=answer_parts.append,
            should_stop=self._stop_event.is_set,
        )
        return "".join(answer_parts).strip()

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

            if self.followup_resolution.needs_clarification:
                if self.trace is not None:
                    self.trace.add_metadata(
                        followup_resolution="clarification",
                        web_request_skipped=True,
                    )
                self.token.emit(self._followup_clarification())
                self.finished.emit()
                return

            if self.trace is not None:
                self.trace.mark_duration(
                    "request_classification",
                    self._classification_ms,
                )
            self.phase.emit(
                "Brave LLM Context"
                if brave_context_mode() == "llm_context"
                else "Webes keresés"
            )

            generic_shopping_mode = (
                is_generic_shopping_request(self.user_prompt)
                and not self._has_multiple_research_topics()
                and not evidence_required(build_search_plan(self.user_prompt))
            )
            if generic_shopping_mode:
                generated_queries = build_generic_shopping_queries(
                    self.user_prompt
                )
                if self.trace is not None:
                    self.trace.mark_duration("query_generation", 0.0)
                    self.trace.add_metadata(query_strategy="generic_shopping")
            elif (
                self.followup_resolution.status == "direct"
                and is_factual_risk_request(self.user_prompt)
                and not self._has_multiple_research_topics()
            ):
                if self.trace is not None:
                    self.trace.begin("query_derivation")
                neutral_query, self._direct_query_strategy = (
                    derive_premise_neutral_query(
                        self.user_prompt,
                        self.request_profile.requested_fact,
                    )
                )
                generated_queries = [neutral_query]
                if self.trace is not None:
                    self.trace.end("query_derivation")
                    self.trace.mark_duration("query_generation", 0.0)
                    self.trace.add_metadata(
                        query_strategy=self._direct_query_strategy,
                    )
            elif (
                self.followup_resolution.status == "direct"
                and self.request_profile.kind == TASK_ENTITY_OVERVIEW
                and not self._has_multiple_research_topics()
            ):
                generated_queries = [self.user_prompt]
                if self.trace is not None:
                    self.trace.mark_duration("query_generation", 0.0)
                    self.trace.add_metadata(query_strategy="entity_overview_direct")
            else:
                if self.trace is not None:
                    self.trace.begin("query_generation")
                generated_queries = self._generate_search_queries()
                if self.trace is not None:
                    self.trace.end(
                        "query_generation",
                        query_strategy="model_generated",
                    )
            queries = self._validated_search_queries(generated_queries)
            if self.trace is not None:
                self.trace.add_metadata(
                    followup_resolution=self.followup_resolution.status,
                    query_validation=self.query_validation["status"],
                    rejected_query_count=len(self.query_validation["rejections"]),
                )
            if not queries:
                if self.trace is not None:
                    self.trace.mark_duration("search_provider", 0.0)
                self.token.emit(self._invalid_query_clarification())
                self.finished.emit()
                return
            if self.trace is not None:
                self.trace.begin("search")
                self.trace.begin("search_provider")
            generic_shopping_records = []
            generic_shopping_queries = []
            generic_shopping_providers = []
            contexts = []
            factual_payloads = []
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
            context_modes = []
            evidence_sufficiency = "not_applicable"
            direct_fact_progressive = (
                self.request_profile.kind == TASK_DIRECT_FACT
                and self.followup_resolution.status == "direct"
                and len(queries) == 1
                and not generic_shopping_mode
            )

            for query in queries:
                if self._stop_event.is_set():
                    self.finished.emit()
                    return

                payload_queries = [query]
                try:
                    payload = self._search_payload(
                        query,
                        max_results=(
                            10
                            if generic_shopping_mode
                            else self.request_profile.source_budget
                        ),
                        fetch_pages=(
                            True
                            if generic_shopping_mode
                            else (0 if direct_fact_progressive else self.request_profile.page_fetch_budget)
                        ),
                    )
                    snippet_supported = requested_fact_supported(
                        payload,
                        self.request_profile.requested_fact,
                        self.user_prompt,
                    )
                    if (
                        direct_fact_progressive
                        and not snippet_supported
                    ):
                        payload = self._fetch_direct_fact_page(payload)
                        evidence_sufficiency = (
                            "page_supported"
                            if requested_fact_supported(
                                payload,
                                self.request_profile.requested_fact,
                                self.user_prompt,
                            )
                            else "insufficient_after_one_page"
                        )
                        if evidence_sufficiency == "insufficient_after_one_page":
                            refinement_query = targeted_fact_refinement_query(
                                self.user_prompt,
                                self.request_profile.requested_fact,
                            )
                            if refinement_query and refinement_query != query:
                                try:
                                    refinement = self._search_payload(
                                        refinement_query,
                                        max_results=self.request_profile.source_budget,
                                        fetch_pages=0,
                                    )
                                    payload = self._merge_direct_fact_payloads(
                                        payload,
                                        refinement,
                                    )
                                    payload_queries.append(refinement_query)
                                    evidence_sufficiency = (
                                        "targeted_search_supported"
                                        if requested_fact_supported(
                                            refinement,
                                            self.request_profile.requested_fact,
                                            self.user_prompt,
                                        )
                                        else "insufficient_after_targeted_search"
                                    )
                                except Exception as refinement_exc:
                                    failed_queries.append(
                                        f"{refinement_query}: "
                                        f"{self._compact_web_error(refinement_exc)}"
                                    )
                    elif direct_fact_progressive:
                        evidence_sufficiency = "snippet_supported"
                    if self.trace is not None:
                        timing = dict(payload.get("timing") or {})
                        self.trace.add_duration(
                            "search_provider_time",
                            timing.get("provider_ms", 0.0),
                        )
                        self.trace.add_duration(
                            "page_fetch",
                            timing.get("page_fetch_ms", 0.0),
                        )
                        if payload.get("context_mode") == "llm_context":
                            self.trace.add_duration(
                                "llm_context",
                                timing.get("provider_ms", 0.0),
                            )
                    mode = str(payload.get("context_mode") or "legacy")
                    if mode not in context_modes:
                        context_modes.append(mode)
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

                for completed_query in payload_queries:
                    if completed_query not in successful_queries:
                        successful_queries.append(completed_query)
                factual_payloads.append(dict(payload))
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

                for entry in source_entries(
                    payload,
                    limit=min(self.request_profile.source_budget, 12),
                ):
                    if entry["url"] not in {
                        item["url"] for item in entries
                    }:
                        entries.append(entry)

            if self.trace is not None:
                self.trace.end("search_provider")
                self.trace.end(
                    "search",
                    successful_queries=len(
                        successful_queries or generic_shopping_queries
                    ),
                    provider_count=len(
                        successful_providers or generic_shopping_providers
                    ),
                )
            self.phase.emit("Források feldolgozása")

            if generic_shopping_mode:
                answer = render_generic_shopping_answer(
                    self.user_prompt,
                    generic_shopping_records,
                )
                self.source_metadata = [
                    {
                        "title": str(item.get("title") or "Source").strip(),
                        "url": str(item.get("url") or "").strip(),
                    }
                    for item in generic_shopping_records[:12]
                    if str(item.get("url") or "").strip()
                ]
                self._set_diagnostics(
                    queries=generic_shopping_queries,
                    providers=generic_shopping_providers,
                    provider_fallbacks=provider_fallback_notes,
                    evidence_ledger_count=len(evidence_ledgers),
                    context_modes=context_modes,
                )
                self.token.emit(answer)
                self.finished.emit()
                return

            if not contexts or not urls:
                if self.synthesis_route == SYNTHESIS_HYBRID:
                    if self.trace is not None:
                        self.trace.begin("model_inference")
                    answer = self._hybrid_without_usable_sources()
                    if self.trace is not None:
                        self.trace.end("model_inference")
                    if answer:
                        if self.trace is not None:
                            self.trace.begin("post_processing")
                        answer = self._repair_response_language(answer)
                        # With no usable web evidence, a hybrid answer may still
                        # explain stable concepts but cannot introduce a fresh
                        # literal absent from the user's own request.
                        answer = guard_grounded_answer(
                            self.client,
                            self.model,
                            self.user_prompt,
                            answer,
                            self.user_prompt,
                            trace=self.trace,
                            language_instruction=self._conversation_language_instruction(),
                            output_budget=self.output_budget,
                        )
                        if self.trace is not None:
                            self.trace.end("post_processing")
                        self._set_diagnostics(
                            queries=queries,
                            providers=successful_providers,
                            provider_fallbacks=provider_fallback_notes,
                            evidence_ledger_count=len(evidence_ledgers),
                            context_modes=context_modes,
                            verification_status="HYBRID stable synthesis; web augmentation unavailable",
                            evidence_coverage="unavailable_for_web_augmentation",
                        )
                        self.diagnostic_metadata.update({
                            "failure_code": "no_usable_public_sources",
                            "failure_detail": "Web augmentation returned no usable public sources.",
                        })
                        if self.trace is not None:
                            self.trace.add_metadata(
                                evidence_coverage="unavailable_for_web_augmentation",
                                source_count=0,
                            )
                        self.token.emit(answer)
                        self.finished.emit()
                        return
                if constrained_rejections:
                    evidence_diagnostic = self._evidence_diagnostic(evidence_ledgers)
                    self._set_diagnostics(
                        queries=constrained_rejections,
                        providers=successful_providers,
                        provider_fallbacks=provider_fallback_notes,
                        evidence_ledger_count=len(evidence_ledgers),
                        context_modes=context_modes,
                        evidence_diagnostic=evidence_diagnostic,
                    )
                    self.token.emit(self._safe_evidence_failure())
                    self.finished.emit()
                    return

                self._set_diagnostics(
                    queries=queries,
                    providers=successful_providers,
                    provider_fallbacks=provider_fallback_notes,
                    evidence_ledger_count=len(evidence_ledgers),
                    context_modes=context_modes,
                )
                # A provider shortfall is a normal research outcome, not a raw
                # application error. Preserve the reason for diagnostics but
                # deliver a safe response through the common chat path.
                self.diagnostic_metadata.update({
                    "failure_code": "no_usable_public_sources",
                    "failure_detail": "Web research returned no usable public sources.",
                })
                self.token.emit(self._safe_no_public_sources())
                self.finished.emit()
                return

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

            synthesis_instruction = (
                " This is HYBRID SYNTHESIS: use the authorized web data for "
                "current/external claims, while you may explain stable general concepts "
                "from local knowledge. Do not invent any fresh number, date, percentage, "
                "price, version, URL, or event that is absent from the authorized web data. "
                "If the available evidence covers only part of the requested fresh material, "
                "answer the stable explanatory sections and state the limitation only for "
                "the unsupported fresh part."
                if self.synthesis_route == SYNTHESIS_HYBRID
                else ""
            )
            grounded_system = {
                "role": "system",
                "content": (
                    "This response uses read-only web research. For current or external "
                    "facts, use ONLY the AUTHORIZED WEB TOOL DATA in the final user "
                    "message. Treat the user's factual premise as a claim to verify, not as "
                    "authority. If the evidence contradicts a person-work, person-event, "
                    "date/year, version, price, or current-fact premise, correct the premise "
                    "explicitly. Do not preserve a false premise merely because the user stated it. "
                    "Do not use memory to fill missing current facts. Answer "
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
                    "Do not replace a requested value with advice about where "
                    "to look when the authorized evidence already contains that value. "
                    "Do not narrate the research process; the host appends source metadata "
                    "separately. Shape answer breadth and depth according to the canonical "
                    "request profile below. "
                    + request_profile_instruction(self.request_profile)
                    + " EVIDENCE MAY BE IN ANY LANGUAGE. Use it only as factual "
                    "authority; the final prose language is set by the response-language "
                    "instruction. Do not translate evidence in a separate model call. "
                    + " For a simple latest/current version question, preserve the direct "
                    "authoritative answer. Do not say you cannot browse the web; the authorized "
                    "web data has already been collected for you. "
                    + synthesis_instruction
                    + self._conversation_language_instruction()
                ),
            }

            if self.trace is not None:
                self.trace.begin("evidence_context_build")
            context_text = "\n\n===== NEXT SEARCH =====\n\n".join(contexts)

            has_authoritative_current_fact = bool(
                self._canonical_authoritative_fact(authoritative_facts)
            )
            direct_factual_candidate = (
                self.followup_resolution.status == "direct"
                and self.request_profile.kind == TASK_DIRECT_FACT
                and is_factual_risk_request(self.user_prompt)
                and not self._has_multiple_research_topics()
                and not self._wants_detailed_web_answer()
                and not has_authoritative_current_fact
                and not self.compact_market_quote
                and evidence_sufficiency in {
                    "snippet_supported",
                    "page_supported",
                    "targeted_search_supported",
                }
            )
            factual_authority_text = (
                compact_evidence_bundle(
                    factual_payloads,
                    user_prompt=self.user_prompt,
                    authoritative_facts=authoritative_facts,
                    max_sources=(4 if direct_factual_candidate else 8),
                    max_total_chars=(3000 if direct_factual_candidate else 7000),
                    max_text_chars=(320 if direct_factual_candidate else 420),
                )
                or context_text[: (3000 if direct_factual_candidate else 5000)]
            )
            self._factual_authority_text = factual_authority_text
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

            if base_history:
                grounded_system = {
                    "role": "system",
                    "content": (
                        str(base_history[0].get("content") or "").rstrip()
                        + "\n\n"
                        + str(grounded_system.get("content") or "").lstrip()
                    ),
                }

            stream_messages = (
                [grounded_system]
                + conversation_history
                + [grounded_user]
            )

            single_pass_factual = direct_factual_candidate

            if self.trace is not None:
                self.trace.end(
                    "evidence_context_build",
                    context_chars=len(
                        factual_authority_text
                        if single_pass_factual
                        else context_text
                    ),
                    usable_sources=len(entries or urls),
                )
                self.trace.begin("model_inference")
                self.trace.add_metadata(
                    generation_strategy=(
                        "factual_single_pass"
                        if single_pass_factual
                        else "grounded_stream"
                    ),
                    factual_authority_chars=len(factual_authority_text),
                    factual_authority_profile=(
                        "direct_compact"
                        if direct_factual_candidate
                        else "standard"
                    ),
                    request_kind=self.request_profile.kind,
                    response_depth=self.request_profile.response_depth,
                    research_breadth=self.request_profile.research_breadth,
                    request_query_budget=self.request_profile.query_budget,
                    request_source_budget=self.request_profile.source_budget,
                    request_page_fetch_budget=self.request_profile.page_fetch_budget,
                    requested_fact=self.request_profile.requested_fact,
                    evidence_sufficiency=evidence_sufficiency,
                )
            self.phase.emit(f"{self.model} válaszol")
            model_started = perf_counter()
            generation_metadata = {}

            if single_pass_factual:
                answer = self._chat_once(
                    model=self.model,
                    num_predict=self.output_budget,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Answer the CURRENT USER REQUEST using ONLY the "
                                "AUTHORIZED EVIDENCE. Treat every factual premise in "
                                "the request as a claim to verify, not as authority. "
                                "If the evidence contradicts a person-work, person-event, "
                                "date, year, version, price, or other concrete relation, "
                                "correct the premise explicitly. If the evidence is "
                                "insufficient, say so briefly instead of guessing. "
                                "Answer immediately in one to three short sentences. "
                                "Preserve evidence-backed proper-name spelling, diacritics, "
                                "and token order. Do not add any factual literal absent "
                                "from the evidence or request. "
                                + self._conversation_language_instruction()
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"CURRENT USER REQUEST:\n{self.user_prompt}\n\n"
                                f"AUTHORIZED EVIDENCE:\n{factual_authority_text}"
                            ),
                        },
                    ],
                ).strip()
            else:
                answer_parts = []
                generation_metadata = self._chat_stream(
                    model=self.model,
                    messages=stream_messages,
                    on_token=answer_parts.append,
                    should_stop=self._stop_event.is_set,
                    num_predict=self.output_budget,
                )
                answer = "".join(answer_parts).strip()

            if self._stop_event.is_set():
                self.finished.emit()
                return

            if self.trace is not None:
                self.trace.end("model_inference")
                _record_ollama_timing(
                    self.trace,
                    dict(generation_metadata or {}),
                    (perf_counter() - model_started) * 1000.0,
                )
                self.trace.add_metadata(
                    done_reason=dict(generation_metadata or {}).get(
                        "done_reason", ""
                    ),
                    generated_count=dict(generation_metadata or {}).get(
                        "eval_count"
                    ),
                )
                self.trace.begin("post_processing")
            self.phase.emit("Evidence ellenőrzése")

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
            if self.trace is not None:
                self.trace.begin("factual_validation")
            answer = guard_grounded_answer(
                self.client,
                self.model,
                self.user_prompt,
                answer,
                self.user_prompt + "\n\n" + factual_authority_text,
                trace=self.trace,
                force_verify=(
                    is_factual_risk_request(self.user_prompt)
                    and not has_authoritative_current_fact
                    and not single_pass_factual
                ),
                language_instruction=self._conversation_language_instruction(),
                output_budget=self.output_budget,
            )
            if self.trace is not None:
                self.trace.end("factual_validation")
            if (
                is_factual_risk_request(self.user_prompt)
                and not has_authoritative_current_fact
            ):
                if self.trace is not None:
                    self.trace.begin("context_validation")
                answer = guard_current_turn_binding(
                    self.client,
                    self.model,
                    self.user_prompt,
                    answer,
                    factual_authority_text,
                    trace=self.trace,
                    language_instruction=self._conversation_language_instruction(),
                )
                if self.trace is not None:
                    self.trace.end("context_validation")

            verification_status = ""
            unique_verification_queries = list(dict.fromkeys(verification_queries))
            if (
                len(unique_verification_queries) == 1
                and self.synthesis_route != SYNTHESIS_HYBRID
            ):
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
            elif self.synthesis_route == SYNTHESIS_HYBRID:
                verification_status = (
                    "HYBRID evidence coverage: web claims guarded; stable synthesis allowed"
                )

            if self.trace is not None:
                self.trace.end("post_processing")

            self.source_metadata = [
                {
                    "title": str(item.get("title") or "Source").strip(),
                    "url": str(item.get("url") or "").strip(),
                }
                for item in entries[:12]
                if str(item.get("url") or "").strip()
            ]
            if not self.source_metadata:
                self.source_metadata = [
                    {"title": url, "url": url}
                    for url in urls[:12]
                    if str(url or "").strip()
                ]
            self._set_diagnostics(
                queries=successful_queries,
                providers=successful_providers,
                provider_fallbacks=provider_fallback_notes,
                evidence_ledger_count=len(evidence_ledgers),
                context_modes=context_modes,
                verification_status=verification_status,
                evidence_coverage=(
                    "partial_or_available"
                    if self.synthesis_route == SYNTHESIS_HYBRID
                    else "required"
                ),
            )
            self.diagnostic_metadata.update({
                "done_reason": dict(generation_metadata or {}).get(
                    "done_reason", ""
                ),
                "generated_count": dict(generation_metadata or {}).get(
                    "eval_count"
                ),
            })
            if self.trace is not None:
                self.trace.add_metadata(
                    web_provider=",".join(successful_providers),
                    source_count=len(self.source_metadata),
                    context_mode=",".join(context_modes),
                    model_call_count=self.execution_control.budget.model_calls,
                    search_count=self.execution_control.budget.search_calls,
                    page_fetch_count=self.execution_control.budget.page_fetches,
                    repair_count=self.execution_control.budget.repairs,
                )
            self.token.emit(answer)
            self.finished.emit()
        except Exception as exc:
            _record_ollama_failure(self.trace, exc)
            self.failed.emit(str(exc))

    def stop(self):
        self._stop_event.set()
        self.execution_control.cancellation.cancel()


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


def run_chat_web_request(
    client,
    model,
    messages,
    user_prompt,
    *,
    trace=None,
    explicit_batch_child=False,
    output_budget=None,
    synthesis_route=None,
):
    """Run the existing grounded web worker synchronously and collect its answer."""
    return _run_web_worker(
        ChatWebWorker(
            client,
            model,
            messages,
            user_prompt,
            trace=trace,
            explicit_batch_child=explicit_batch_child,
            output_budget=output_budget,
            synthesis_route=synthesis_route,
        )
    )


def run_market_web_request(
    client,
    model,
    messages,
    user_prompt,
    *,
    trace=None,
    explicit_batch_child=False,
):
    """Run concise grounded web fallback for a live market-value lookup."""
    return _run_web_worker(
        ChatWebWorker(
            client,
            model,
            messages,
            user_prompt,
            compact_market_quote=True,
            trace=trace,
            explicit_batch_child=explicit_batch_child,
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
    phase = Signal(str)
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
        trace=None,
        explicit_batch_child=False,
        output_budget=None,
        synthesis_route=SYNTHESIS_LOCAL,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.allow_web_fallback = bool(allow_web_fallback)
        self.constraints = constraints
        self.trace = trace
        self.explicit_batch_child = bool(explicit_batch_child)
        default_generation_policy = build_generation_policy(
            self.user_prompt,
            profile=getattr(constraints, "request_profile", None),
            use_web=False,
        )
        self.output_budget = max(
            1,
            int(output_budget or default_generation_policy.output_budget),
        )
        self.response_length = default_generation_policy.response_length
        self.synthesis_route = str(synthesis_route or SYNTHESIS_LOCAL).upper()
        if self.synthesis_route not in {SYNTHESIS_LOCAL, SYNTHESIS_WEB, SYNTHESIS_HYBRID}:
            self.synthesis_route = SYNTHESIS_LOCAL
        self._stop_event = threading.Event()
        self.execution_control = ExecutionControl()
        self.used_web_fallback = False
        self.raw_model_output = ""
        self.final_output = ""
        self.generation_metadata = {}
        self.diagnostic_metadata = {}
        if self.trace is not None:
            self.trace.add_metadata(
                synthesis_route=self.synthesis_route,
                response_length=self.response_length,
                output_budget=self.output_budget,
                web_required=False,
            )

    @Slot()
    def run(self):
        try:
            if self._stop_event.is_set():
                self.finished.emit()
                return

            if self.trace is not None:
                self.trace.begin("model_inference")
                self.trace.begin("primary_generation")
            self.phase.emit(f"{self.model} válaszol")
            model_started = perf_counter()

            if isinstance(self.client, OllamaClient):
                draft_parts = []
                metadata = self.client.chat_stream(
                    model=self.model,
                    messages=self.messages,
                    on_token=draft_parts.append,
                    should_stop=self._stop_event.is_set,
                    control=self.execution_control,
                    num_predict=self.output_budget,
                    call_phase="primary_generation",
                )
                draft = "".join(draft_parts).strip()
                self.generation_metadata = dict(metadata or {})
            else:
                draft = self.client.chat_once(
                    model=self.model,
                    messages=self.messages,
                ).strip()
                self.generation_metadata = {}
            self.raw_model_output = draft

            if self.trace is not None:
                self.trace.end("model_inference")
                self.trace.end("primary_generation", primary_generation_result="completed")
                _record_ollama_timing(
                    self.trace,
                    self.generation_metadata,
                    (perf_counter() - model_started) * 1000.0,
                )
                self.trace.add_metadata(
                    done_reason=self.generation_metadata.get("done_reason", ""),
                    generated_count=self.generation_metadata.get("eval_count"),
                )
                self.trace.begin("post_processing")

            if (
                self.allow_web_fallback
                and not self._stop_event.is_set()
                and answer_requires_web_fallback(self.user_prompt, draft)
            ):
                self.used_web_fallback = True
                self.phase.emit("Webes keresés")
                if self.trace is not None:
                    self.trace.end("post_processing")
                if self.trace is None:
                    web_kwargs = (
                        {"explicit_batch_child": True}
                        if self.explicit_batch_child
                        else {}
                    )
                    if isinstance(self.client, OllamaClient):
                        web_kwargs.update({
                            "output_budget": self.output_budget,
                            "synthesis_route": SYNTHESIS_WEB,
                        })
                    final = run_chat_web_request(
                        self.client,
                        self.model,
                        self.messages,
                        self.user_prompt,
                        **web_kwargs,
                    ).strip()
                else:
                    web_kwargs = {"trace": self.trace}
                    if self.explicit_batch_child:
                        web_kwargs["explicit_batch_child"] = True
                    if isinstance(self.client, OllamaClient):
                        web_kwargs.update({
                            "output_budget": self.output_budget,
                            "synthesis_route": SYNTHESIS_WEB,
                        })
                    final = run_chat_web_request(
                        self.client,
                        self.model,
                        self.messages,
                        self.user_prompt,
                        **web_kwargs,
                    ).strip()
                if self.trace is not None:
                    self.trace.begin("post_processing")
                    self.trace.add_metadata(
                        synthesis_route=SYNTHESIS_WEB,
                        web_required=True,
                    )
            else:
                final = draft

            if self.constraints is not None:
                self.phase.emit("Ellenőrzés")
                final = guard_response(
                    self.client,
                    self.model,
                    self.user_prompt,
                    final,
                    constraints=self.constraints,
                    control=self.execution_control,
                    output_budget=self.output_budget,
                    trace=self.trace,
                    phase_callback=self.phase.emit,
                )
                final = guard_context_response(
                    self.client,
                    self.model,
                    self.user_prompt,
                    final,
                    self.messages,
                    constraints=self.constraints,
                    control=self.execution_control,
                    output_budget=self.output_budget,
                )

            if self._stop_event.is_set():
                self.finished.emit()
                return

            self.final_output = final
            self.diagnostic_metadata = {
                "response_pipeline": {
                    "raw_chars": len(self.raw_model_output),
                    "final_chars": len(self.final_output),
                    "raw_final_equal": self.raw_model_output == self.final_output,
                    "raw_sha256": hashlib.sha256(
                        self.raw_model_output.encode("utf-8")
                    ).hexdigest()[:16],
                    "final_sha256": hashlib.sha256(
                        self.final_output.encode("utf-8")
                    ).hexdigest()[:16],
                    "done_reason": self.generation_metadata.get("done_reason", ""),
                    "prompt_eval_count": self.generation_metadata.get("prompt_eval_count"),
                    "eval_count": self.generation_metadata.get("eval_count"),
                    "synthesis_route": self.synthesis_route,
                    "response_length": self.response_length,
                    "output_budget": self.output_budget,
                }
            }

            if self.trace is not None:
                self.trace.end("post_processing")
            if final:
                self.token.emit(final)
            self.finished.emit()
        except Exception as exc:
            _record_ollama_failure(self.trace, exc)
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
        explicit_batch_child=False,
    ):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = [dict(message) for message in messages]
        self.user_prompt = str(user_prompt or "").strip()
        self.artifact_plans = tuple(artifact_plans or ())
        self.use_web = bool(use_web)
        self.constraints = constraints
        self.explicit_batch_child = bool(explicit_batch_child)
        self._stop_event = threading.Event()
        self.execution_control = ExecutionControl(
            budget=ExecutionBudget(
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
                web_kwargs = (
                    {"explicit_batch_child": True}
                    if self.explicit_batch_child
                    else {}
                )
                source_context = run_chat_web_request(
                    self.client,
                    self.model,
                    self.messages,
                    self.user_prompt,
                    **web_kwargs,
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
                    effective_prompt = str(plan.prompt or self.user_prompt)
                    content = guard_response(
                        self.client,
                        self.model,
                        effective_prompt,
                        content,
                        constraints=self.constraints,
                        control=self.execution_control,
                    )
                    content = guard_context_response(
                        self.client,
                        self.model,
                        effective_prompt,
                        content,
                        self.messages,
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
