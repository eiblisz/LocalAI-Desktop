import threading

from PySide6.QtCore import QObject, Signal, Slot

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

    @Slot()
    def run(self):
        task_id = self.task.get("id", "")
        try:
            prompt = str(self.task.get("prompt", "")).strip()
            model = str(self.task.get("model", "")).strip()
            if not prompt:
                raise RuntimeError("Scheduled task prompt is empty.")
            if not model:
                raise RuntimeError("Scheduled task model is not set.")

            permissions = self.task.get("permissions") or {}
            context_blocks = []

            if permissions.get("weather", False):
                location = str(self.task.get("location", "")).strip()
                weather = get_weather(location)
                context_blocks.append(weather_context_text(weather))

            if not context_blocks:
                raise RuntimeError(
                    "This scheduled task has no enabled data tool. "
                    "Enable Weather or add another allowed tool."
                )

            tool_context = "\n\n".join(context_blocks)
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are running a scheduled local-assistant task. "
                        "You do not have direct internet access. Use only the "
                        "tool data included below for current external facts. "
                        "Do not invent missing live data. Keep the answer concise "
                        "unless the task explicitly asks for detail. Mention the "
                        "data provider when reporting live weather."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"SCHEDULED TASK:\n{prompt}\n\n"
                        f"AUTHORIZED TOOL DATA:\n{tool_context}"
                    ),
                },
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
