import json
from typing import Callable

import requests

from .config import OLLAMA_BASE_URL


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")

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

    def chat_once(
        self,
        model: str,
        messages: list[dict],
        timeout: float = 600.0,
        response_format=None,
    ) -> str:
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
