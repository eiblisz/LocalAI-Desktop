import re
import threading

from PySide6.QtCore import QObject, Signal, Slot

from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .ebay_tool import ebay_context_text, search_ebay
from .ollama_client import OllamaClient
from .weather_tool import get_weather, weather_context_text
from .web_search_tool import (
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

    def _is_research_followup(self):
        normalized = " ".join(self.user_prompt.lower().split())
        markers = [
            "keress rá újra",
            "keress ra ujra",
            "keress újra",
            "keress ujra",
            "nézd meg újra",
            "nezd meg ujra",
            "nézd meg megint",
            "nezd meg megint",
            "keress rá megint",
            "keress ra megint",
            "arra keress",
            "erre keress",
            "ugyanazt",
            "ugyan ezt",
            "próbáld újra",
            "probald ujra",
            "most újra",
            "most ujra",
            "search again",
            "look it up again",
            "try again",
            "same search",
        ]
        return any(marker in normalized for marker in markers)

    def _conversation_language_instruction(self):
        sample_parts = [
            self.user_prompt,
            *self._recent_user_requests(limit=3),
        ]
        sample = " ".join(sample_parts).lower()
        hungarian_markers = [
            " keress", " nézd", " nezd", " most ", " újra", " ujra",
            " alatt", " mennyi", " milyen", " nekem", " legyen",
            " kapható", " kaphato", " ár", " ar ", " videokárty",
            " videokarty", " memória", " memoria",
        ]
        if any(marker in f" {sample} " for marker in hungarian_markers):
            return (
                "The user is speaking Hungarian. The final answer must be in Hungarian."
            )
        return (
            "Answer in the same language the user is using in the conversation."
        )

    def _query_is_literal_followup_command(self, query):
        normalized = " ".join(str(query or "").lower().split())
        bad_markers = [
            "keress ra ujra",
            "keress rá újra",
            "keress ujra",
            "keress újra",
            "nezd meg ujra",
            "nézd meg újra",
            "search again",
            "look it up again",
            "try again",
            "same search",
        ]
        return any(marker in normalized for marker in bad_markers)

    def _generate_search_queries(self):
        prompt = self.user_prompt[:5000]
        recent_requests = self._recent_user_requests()
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
                queries.append(clean[:180])
            if len(queries) >= 4:
                break

        if not queries:
            if self._is_research_followup() and recent_requests:
                queries = [recent_requests[-1][:180]]
            else:
                queries = [self.user_prompt[:180]]
        return queries

    @Slot()
    def run(self):
        try:
            if not self.user_prompt:
                raise RuntimeError("Web chat request is empty.")

            queries = self._generate_search_queries()
            contexts = []
            urls = []
            entries = []
            successful_queries = []
            failed_queries = []

            for query in queries:
                if self._stop_event.is_set():
                    self.finished.emit()
                    return

                try:
                    payload = search_web(
                        query,
                        max_results=6,
                        fetch_pages=True,
                    )
                except Exception as exc:
                    failed_queries.append(f"{query}: {exc}")
                    continue

                query_urls = source_urls(payload)
                if not query_urls:
                    failed_queries.append(
                        f"{query}: no usable public sources"
                    )
                    continue

                successful_queries.append(query)
                contexts.append(
                    f"SEARCH QUERY: {query}\n"
                    f"{web_search_context_text(payload)}"
                )
                for url in query_urls:
                    if url not in urls:
                        urls.append(url)

                for entry in source_entries(payload, limit=6):
                    if entry["url"] not in {
                        item["url"] for item in entries
                    }:
                        entries.append(entry)

            if not contexts or not urls:
                detail = " | ".join(failed_queries[:4])
                raise RuntimeError(
                    "Web research returned no usable public sources."
                    + (f" {detail}" if detail else "")
                )

            history = [dict(message) for message in self.messages]
            if history and history[-1].get("role") == "user":
                history = history[:-1]

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
                    "quotations. Do not answer an adjacent topic. When you mention a "
                    "specific product, offer, article, or result, include its provided "
                    "source URL in the same bullet or sentence using Markdown link syntax. "
                    "Do not say you cannot browse the web; the authorized web data has "
                    "already been collected for you. "
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
                history[:1]
                + [grounded_system]
                + history[1:]
                + [grounded_user]
            )

            self.client.chat_stream(
                model=self.model,
                messages=stream_messages,
                on_token=self.token.emit,
                should_stop=self._stop_event.is_set,
            )

            if self._stop_event.is_set():
                self.finished.emit()
                return

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

            self.token.emit(
                "\n\n---\n"
                f"{query_footer}\n"
                "Web results / sources:\n"
                f"{source_lines}"
            )
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
