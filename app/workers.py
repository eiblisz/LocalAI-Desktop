import threading

from PySide6.QtCore import QObject, Signal, Slot

from .computer_status_tool import (
    computer_status_context_text,
    get_computer_status,
)
from .ebay_tool import ebay_context_text, search_ebay
from .ollama_client import OllamaClient
from .weather_tool import get_weather, weather_context_text


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

    def _build_context(self):
        task_type = str(self.task.get("task_type", "weather")).strip().lower()

        if task_type == "weather":
            location = str(self.task.get("location", "")).strip()
            if not location:
                raise RuntimeError("Weather task requires a location.")
            weather = get_weather(location)
            return weather_context_text(weather)

        if task_type == "ebay":
            query = str(self.task.get("ebay_query", "")).strip()
            if not query:
                raise RuntimeError("eBay Search task requires a search query.")
            payload = search_ebay(
                query,
                max_results=int(self.task.get("ebay_max_results", 8) or 8),
            )
            return ebay_context_text(payload)

        if task_type == "computer":
            return computer_status_context_text(get_computer_status())

        if task_type == "custom":
            return ""

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

            tool_context = self._build_context()

            if tool_context:
                user_content = (
                    f"SCHEDULED TASK TYPE: {task_type}\n"
                    f"SCHEDULED TASK:\n{prompt}\n\n"
                    f"AUTHORIZED TOOL DATA:\n{tool_context}"
                )
                system_content = (
                    "You are running a scheduled local-assistant task. "
                    "You do not have arbitrary internet access. Use only the "
                    "authorized tool data included in the user message for current "
                    "external facts. Do not invent missing live data. Keep the answer "
                    "concise unless the task explicitly asks for detail."
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
            self.finished.emit(task_id, content.strip())
        except Exception as exc:
            self.failed.emit(task_id, str(exc))
