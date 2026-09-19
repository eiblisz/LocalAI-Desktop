import asyncio
import threading
from dataclasses import dataclass

import discord
import requests
from PySide6.QtCore import QObject, Signal

from .config import DEFAULT_SYSTEM_PROMPT
from .language_policy import response_language_instruction


DISCORD_API_BASE = "https://discord.com/api/v10"


def _snowflake(value, label):
    text = str(value or "").strip()
    if not text.isdigit() or len(text) < 15 or len(text) > 22:
        raise ValueError(f"{label} must be a Discord numeric ID")
    return int(text)


def split_discord_text(text, limit=1900):
    text = str(text or "").strip()
    if not text:
        return ["(empty response)"]
    if limit < 100:
        raise ValueError("Discord chunk limit is too small")

    chunks = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def validate_bot_token(token):
    token = str(token or "").strip()
    if len(token) < 30 or any(char.isspace() for char in token):
        raise ValueError("Discord bot token is invalid")
    return token


def test_discord_bot_token(token, requester=requests.get, timeout=10):
    token = validate_bot_token(token)
    try:
        response = requester(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=float(timeout),
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord bot connection failed: {exc}",
        }

    code = int(getattr(response, "status_code", 0) or 0)
    if code != 200:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord bot token was rejected (HTTP {code or 'unknown'}).",
        }

    try:
        body = response.json()
    except Exception:
        body = {}
    username = str(body.get("username", "") or "Discord bot").strip()
    bot_id = str(body.get("id", "") or "").strip()
    return {
        "status": "connected",
        "ok": True,
        "message": f"Discord bot authenticated as {username} ({bot_id}).",
    }


@dataclass(frozen=True)
class DiscordBotSettings:
    extension_id: str
    name: str
    guild_id: int
    channel_id: int
    allowed_user_id: int
    model: str

    @classmethod
    def from_extension(cls, extension, fallback_model=""):
        extension = dict(extension or {})
        config = dict(extension.get("config") or {})
        model = str(config.get("model") or fallback_model or "").strip()
        if not model or model.startswith("No Ollama"):
            raise ValueError("Discord bot requires an Ollama model")

        return cls(
            extension_id=str(extension.get("id", "") or "").strip(),
            name=str(extension.get("name", "") or "Discord Bot").strip(),
            guild_id=_snowflake(config.get("guild_id"), "Guild ID"),
            channel_id=_snowflake(config.get("channel_id"), "Channel ID"),
            allowed_user_id=_snowflake(config.get("allowed_user_id"), "Allowed User ID"),
            model=model,
        )

    @property
    def fingerprint(self):
        return (
            self.extension_id,
            self.guild_id,
            self.channel_id,
            self.allowed_user_id,
            self.model,
        )


class DiscordBotBridge(QObject):
    status_changed = Signal(str)
    chat_updated = Signal(str)

    def __init__(self, ollama_client, chat_store, settings, token, parent=None):
        super().__init__(parent)
        self.ollama_client = ollama_client
        self.chat_store = chat_store
        self.settings = settings
        self.token = validate_bot_token(token)
        self._thread = None
        self._loop = None
        self._discord_client = None
        self._stopping = threading.Event()

    @property
    def fingerprint(self):
        return self.settings.fingerprint

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.is_running():
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="LocalAI-DiscordBot",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=3.0):
        self._stopping.set()
        client = self._discord_client
        loop = self._loop
        if client is not None and loop is not None and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                future.result(timeout=max(0.5, float(timeout)))
            except Exception:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.5, float(timeout)))
        self._thread = None
        self._discord_client = None
        self._loop = None

    def _thread_main(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            if not self._stopping.is_set():
                self.status_changed.emit(f"Discord bot stopped: {exc}")

    async def _run(self):
        self._loop = asyncio.get_running_loop()
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._discord_client = client
        request_lock = asyncio.Lock()

        @client.event
        async def on_ready():
            identity = str(client.user) if client.user else self.settings.name
            self.status_changed.emit(
                f"Discord bot online: {identity} | channel {self.settings.channel_id}"
            )

        @client.event
        async def on_message(message):
            if not self._message_allowed(message):
                return

            content = str(getattr(message, "content", "") or "").strip()
            if not content:
                if getattr(message, "attachments", None):
                    await message.reply(
                        "A Discord fajlbeolvasas meg nincs bekapcsolva ebben a verzioban.",
                        mention_author=False,
                    )
                return

            async with request_lock:
                try:
                    async with message.channel.typing():
                        answer, chat_id = await asyncio.to_thread(
                            self._answer_prompt,
                            content,
                        )
                    for chunk in split_discord_text(answer):
                        await message.reply(chunk, mention_author=False)
                    self.chat_updated.emit(chat_id)
                except Exception as exc:
                    compact = " ".join(str(exc).split())[:500]
                    self.status_changed.emit(f"Discord request failed: {compact}")
                    try:
                        await message.reply(
                            f"LocalAI hiba: {compact}",
                            mention_author=False,
                        )
                    except Exception:
                        pass

        await client.start(self.token)

    def _message_allowed(self, message):
        author = getattr(message, "author", None)
        if author is None or bool(getattr(author, "bot", False)):
            return False

        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        if guild is None or channel is None:
            return False

        return (
            int(getattr(guild, "id", 0) or 0) == self.settings.guild_id
            and int(getattr(channel, "id", 0) or 0) == self.settings.channel_id
            and int(getattr(author, "id", 0) or 0) == self.settings.allowed_user_id
        )

    def _load_remote_chat(self):
        for chat in self.chat_store.list_chats(include_closed=True):
            if (
                str(chat.get("discord_bot_extension_id", "") or "")
                == self.settings.extension_id
            ):
                return chat

        chat = self.chat_store.new_chat(self.settings.model)
        chat["title"] = f"[DISCORD] {self.settings.name}"[:80]
        chat["model"] = self.settings.model
        chat["discord_bot_extension_id"] = self.settings.extension_id
        self.chat_store.save(chat)
        return chat

    def _answer_prompt(self, prompt):
        chat = self._load_remote_chat()
        chat["model"] = self.settings.model
        chat["messages"].append({"role": "user", "content": prompt})
        self.chat_store.save(chat)

        system_prompt = (
            f"{DEFAULT_SYSTEM_PROMPT}\n\n"
            f"{response_language_instruction(prompt)}\n\n"
            "This request arrived through the authenticated Discord remote bridge. "
            "The Discord user, guild and channel were allowlisted by the LocalAI owner. "
            "This bridge version provides conversational access only. Do not claim to "
            "have executed shell commands, files, external tools, or extensions unless "
            "their actual results are explicitly supplied in the conversation."
        )
        messages = [{"role": "system", "content": system_prompt}]
        history = [
            item for item in chat.get("messages", [])
            if item.get("role") in {"user", "assistant"}
        ][-24:]
        messages.extend(history)

        answer = self.ollama_client.chat_once(
            model=self.settings.model,
            messages=messages,
        ).strip()
        if not answer:
            answer = "A helyi modell ures valaszt adott."

        chat["messages"].append({"role": "assistant", "content": answer})
        self.chat_store.save(chat)
        return answer, str(chat.get("id", ""))
