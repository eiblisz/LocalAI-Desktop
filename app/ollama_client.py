import json
from typing import Callable

import requests

from .config import OLLAMA_BASE_URL
from .ollama_process_control import kill_ollama_model_processes
from .vram_release import loaded_ollama_models, unload_ollama_model


class OllamaClient:
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        *,
        auto_prepare_model: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.auto_prepare_model = bool(auto_prepare_model)

    def is_available(self, timeout: float = 2.0) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            return response.ok
        except requests.RequestException:
            return False

    def list_models(self, timeout: float = 5.0) -> list[str]:
        response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return [item["name"] for item in payload.get("models", []) if item.get("name")]

    def prepare_model(self, model: str, timeout: float = 6.0) -> list[str]:
        """Unload stale models before a request; recover a stuck runner if needed."""
        target = str(model or "").strip()
        if not target:
            raise ValueError("A target Ollama model is required.")

        try:
            loaded = loaded_ollama_models(
                self,
                timeout=min(float(timeout), 2.5),
            )
        except requests.RequestException:
            try:
                kill_ollama_model_processes(
                    timeout=min(float(timeout), 8.0)
                )
            except Exception:
                pass
            loaded = []

        stale = [name for name in loaded if name and name != target]
        if not stale:
            return []

        released = []
        try:
            for name in stale:
                unload_ollama_model(
                    self,
                    name,
                    timeout=min(float(timeout), 5.0),
                )
                released.append(name)
        except requests.RequestException:
            # A wedged model runner can make keep_alive=0 unresponsive.
            # Kill only runner processes; keep the Ollama server alive.
            kill_ollama_model_processes(timeout=min(float(timeout), 8.0))
        return released

    def chat_once(
        self,
        model: str,
        messages: list[dict],
        timeout: float = 600.0,
        response_format=None,
    ) -> str:
        if self.auto_prepare_model:
            self.prepare_model(model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if response_format is not None:
            if not isinstance(response_format, (str, dict)):
                raise TypeError("response_format must be a string, object, or None.")
            payload["format"] = response_format
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        item = response.json()
        return item.get("message", {}).get("content", "")

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        on_token: Callable[[str], None],
        should_stop: Callable[[], bool],
        timeout: float = 600.0,
    ) -> None:
        if self.auto_prepare_model:
            self.prepare_model(model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        with requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                if should_stop():
                    return
                if not raw_line:
                    continue
                item = json.loads(raw_line.decode("utf-8"))
                chunk = item.get("message", {}).get("content", "")
                if chunk:
                    on_token(chunk)
                if item.get("done"):
                    return
