import json
from pathlib import Path

from .runtime_paths import runtime_root


DEFAULT_WEB_MODE = "ON"
WEB_MODES = frozenset({"AUTO", "ON", "OFF"})


def normalize_web_mode(value, default=DEFAULT_WEB_MODE):
    mode = str(value or "").strip().upper()
    return mode if mode in WEB_MODES else default


class DesktopPreferences:
    """Small, non-secret Desktop preferences store outside individual chats."""

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else runtime_root()

    @property
    def path(self):
        return self.root / "desktop_preferences.json"

    def load(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def web_mode(self):
        return normalize_web_mode(self.load().get("web_mode"))

    def set_web_mode(self, value):
        mode = normalize_web_mode(value)
        payload = self.load()
        payload["web_mode"] = mode
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return mode
