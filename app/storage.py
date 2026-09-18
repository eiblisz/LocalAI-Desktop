import json
import uuid
from datetime import datetime
from pathlib import Path

from .config import CHAT_DIR


class ChatStore:
    def __init__(self, root: Path = CHAT_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize(chat: dict) -> dict:
        chat.setdefault("title", "New chat")
        chat.setdefault("model", "")
        chat.setdefault("messages", [])
        attached = chat.setdefault("attached_extensions", [])
        if not isinstance(attached, list):
            chat["attached_extensions"] = []
        else:
            normalized = []
            for extension_id in attached:
                value = str(extension_id or "").strip()
                if value and value not in normalized:
                    normalized.append(value)
            chat["attached_extensions"] = normalized
        chat.setdefault("pinned", False)
        chat.setdefault("closed", False)
        return chat

    def new_chat(self, model: str = "") -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "model": model,
            "created_at": now,
            "updated_at": now,
            "pinned": False,
            "closed": False,
            "attached_extensions": [],
            "messages": [],
        }
        self.save(chat)
        return chat

    def save(self, chat: dict) -> None:
        self._normalize(chat)
        chat["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self.root / f"{chat['id']}.json"
        path.write_text(
            json.dumps(chat, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, chat_id: str) -> dict:
        path = self.root / f"{chat_id}.json"
        return self._normalize(json.loads(path.read_text(encoding="utf-8")))

    def list_chats(self, include_closed: bool = False) -> list[dict]:
        items = []
        for path in self.root.glob("*.json"):
            try:
                chat = self._normalize(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if include_closed or not chat.get("closed", False):
                    items.append(chat)
            except Exception:
                continue

        return sorted(
            items,
            key=lambda x: (
                bool(x.get("pinned", False)),
                x.get("updated_at", ""),
            ),
            reverse=True,
        )

    def rename(self, chat_id: str, title: str) -> dict:
        chat = self.load(chat_id)
        clean = " ".join(title.strip().split())
        if clean:
            chat["title"] = clean[:80]
            self.save(chat)
        return chat

    def set_pinned(self, chat_id: str, pinned: bool) -> dict:
        chat = self.load(chat_id)
        chat["pinned"] = bool(pinned)
        self.save(chat)
        return chat

    def set_closed(self, chat_id: str, closed: bool) -> dict:
        chat = self.load(chat_id)
        chat["closed"] = bool(closed)
        self.save(chat)
        return chat

    @staticmethod
    def infer_title(text: str) -> str:
        one_line = " ".join(text.strip().split())
        if not one_line:
            return "New chat"
        return one_line[:42] + ("..." if len(one_line) > 42 else "")
