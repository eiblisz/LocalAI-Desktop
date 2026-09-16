import json
import uuid
from datetime import datetime
from pathlib import Path

from .config import CHAT_DIR


class ChatStore:
    def __init__(self, root: Path = CHAT_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def new_chat(self, model: str = "") -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        chat = {
            "id": uuid.uuid4().hex,
            "title": "New chat",
            "model": model,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        self.save(chat)
        return chat

    def save(self, chat: dict) -> None:
        chat["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self.root / f"{chat['id']}.json"
        path.write_text(
            json.dumps(chat, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load(self, chat_id: str) -> dict:
        path = self.root / f"{chat_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def list_chats(self) -> list[dict]:
        items = []
        for path in self.root.glob("*.json"):
            try:
                chat = json.loads(path.read_text(encoding="utf-8"))
                items.append(chat)
            except Exception:
                continue
        return sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)

    @staticmethod
    def infer_title(text: str) -> str:
        one_line = " ".join(text.strip().split())
        if not one_line:
            return "New chat"
        return one_line[:42] + ("..." if len(one_line) > 42 else "")
