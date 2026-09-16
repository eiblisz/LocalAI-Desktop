import threading

from PySide6.QtCore import QObject, Signal, Slot

from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .ebay_tool import ebay_context_text, search_ebay
from .ollama_client import OllamaClient
from .weather_tool import get_weather, weather_context_text
from .web_search_tool import search_web, source_urls, web_search_context_text


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

    def _generate_search_query(self):
        prompt = self.user_prompt[:4000]
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the user's request into one concise web search query. "
                    "Preserve product names, model names, places, dates, and other "
                    "important constraints. Prefer English search terms when that "
                    "improves international web results. Return ONLY the search query, "
                    "with no explanation and no quotation marks."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        query = self.client.chat_once(
            model=self.model,
            messages=messages,
        ).strip()
        query = " ".join(
            query.splitlines()[0].strip().strip('\"\'').split()
        )
        return query[:180] or self.user_prompt[:180]

    @Slot()
    def run(self):
        try:
            if not self.user_prompt:
                raise RuntimeError("Web chat request is empty.")

            query = self._generate_search_query()
            payload = search_web(
                query,
                max_results=8,
                fetch_pages=True,
            )
            urls = source_urls(payload)
            if not urls:
                raise RuntimeError(
                    "Web search returned no usable public sources."
                )

            tool_context = web_search_context_text(payload)

            history = [dict(message) for message in self.messages]
            if history and history[-1].get("role") == "user":
                history = history[:-1]

            grounded_system = {
                "role": "system",
                "content": (
                    "This response uses read-only web research. For current or "
                    "external facts, use ONLY the AUTHORIZED WEB TOOL DATA supplied "
                    "in the final user message. Do not use memory to fill missing "
                    "current facts. If the sources do not support the requested claim "
                    "or topic, say so clearly. Never invent prices, specifications, "
                    "dates, availability, ratings, comparisons, or quotations. "
                    "Answer the user's actual request, not an adjacent topic."
                ),
            }
            grounded_user = {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{self.user_prompt}\n\n"
                    f"AUTHORIZED WEB TOOL DATA:\n{tool_context}"
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

            source_lines = "\n".join(
                f"- {url}" for url in urls[:10]
            )
            self.token.emit(
                "\n\n---\n"
                f"Search query: {query}\n"
                "Sources:\n"
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
