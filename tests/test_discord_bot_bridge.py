from pathlib import Path
from types import SimpleNamespace

import pytest

from app.discord_bot_bridge import (
    DiscordBotBridge,
    DiscordBotSettings,
    split_discord_text,
    test_discord_bot_token as run_bot_token_test,
    validate_bot_token,
)
from app.memory_store import MemoryStore
from app.storage import ChatStore


class Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return dict(self._body)


def test_validate_bot_token_and_rest_identity_probe():
    token = "A" * 40
    assert validate_bot_token(token) == token

    calls = []

    def requester(url, headers, timeout):
        calls.append((url, headers, timeout))
        return Response(200, {"id": "123456789012345678", "username": "Prometheusz"})

    result = run_bot_token_test(token, requester=requester, timeout=4)

    assert result["status"] == "connected"
    assert result["ok"] is True
    assert "Prometheusz" in result["message"]
    assert calls[0][1]["Authorization"] == f"Bot {token}"

    with pytest.raises(ValueError):
        validate_bot_token("short")


def test_discord_bot_settings_require_exact_allowlist_ids_and_model():
    extension = {
        "id": "ext-1",
        "name": "Prometheusz Discord Bot",
        "config": {
            "guild_id": "123456789012345678",
            "channel_id": "223456789012345678",
            "allowed_user_id": "323456789012345678",
            "model": "qwen3-coder:30b",
        },
    }
    settings = DiscordBotSettings.from_extension(extension)

    assert settings.guild_id == 123456789012345678
    assert settings.channel_id == 223456789012345678
    assert settings.allowed_user_id == 323456789012345678
    assert settings.model == "qwen3-coder:30b"

    broken = dict(extension)
    broken["config"] = dict(extension["config"], channel_id="not-an-id")
    with pytest.raises(ValueError):
        DiscordBotSettings.from_extension(broken)


def test_split_discord_text_never_exceeds_limit():
    text = ("abc " * 1500).strip()
    chunks = split_discord_text(text, limit=500)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 500 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ").startswith("abc abc")


def test_message_allowlist_rejects_other_users_channels_guilds_and_bots(tmp_path: Path):
    settings = DiscordBotSettings(
        extension_id="ext",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3",
    )
    bridge = DiscordBotBridge(
        ollama_client=SimpleNamespace(),
        chat_store=ChatStore(tmp_path),
        settings=settings,
        token="T" * 40,
    )

    def message(*, guild=111111111111111111, channel=222222222222222222, user=333333333333333333, bot=False):
        return SimpleNamespace(
            guild=SimpleNamespace(id=guild),
            channel=SimpleNamespace(id=channel),
            author=SimpleNamespace(id=user, bot=bot),
        )

    assert bridge._message_allowed(message())
    assert not bridge._message_allowed(message(user=444444444444444444))
    assert not bridge._message_allowed(message(channel=555555555555555555))
    assert not bridge._message_allowed(message(guild=666666666666666666))
    assert not bridge._message_allowed(message(bot=True))


def test_remote_prompt_uses_dedicated_persistent_discord_chat(tmp_path: Path):
    class FakeOllama:
        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages):
            self.calls.append((model, messages))
            return "Szia Discord!"

    ollama = FakeOllama()
    store = ChatStore(tmp_path)
    settings = DiscordBotSettings(
        extension_id="ext-remote",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=ollama,
        chat_store=store,
        settings=settings,
        token="T" * 40,
    )

    answer, chat_id = bridge._answer_prompt("Szia, itt vagy?")

    assert answer == "Szia Discord!"
    chat = store.load(chat_id)
    assert chat["title"] == "[DISCORD] Prometheusz"
    assert chat["discord_bot_extension_id"] == "ext-remote"
    assert chat["messages"][-2:] == [
        {"role": "user", "content": "Szia, itt vagy?"},
        {"role": "assistant", "content": "Szia Discord!"},
    ]
    system = ollama.calls[0][1][0]["content"]
    assert "authenticated Discord remote bridge" in system
    assert "your interface name is Prometheusz" in system
    assert "Prometheusz is not a separate AI system" in system
    assert "If the user asks whether you are Prometheusz, answer yes" in system
    assert "conversational access only" in system


def test_remote_prompt_answers_direct_user_memory_without_model(tmp_path: Path):
    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("model must not be called for deterministic memory answer")

    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    memory_store.remember_explicit(
        category="USER_PROFILE",
        scope="USER",
        subject="Lilla",
        key="relationship_to_user",
        value="daughter",
        source_chat_id="seed",
        source_excerpt="Jegyezd meg, hogy Lilla a lányom.",
    )

    settings = DiscordBotSettings(
        extension_id="ext-memory",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=FailingOllama(),
        chat_store=ChatStore(tmp_path / "chats"),
        settings=settings,
        token="T" * 40,
        memory_store=memory_store,
    )

    answer, chat_id = bridge._answer_prompt("Ki nekem Lilla?")

    assert answer == "Lilla a lányod."
    chat = bridge.chat_store.load(chat_id)
    assert chat["messages"][-1] == {
        "role": "assistant",
        "content": "Lilla a lányod.",
    }


def test_remote_prompt_injects_relevant_persistent_memory_for_model(tmp_path: Path):
    class FakeOllama:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages):
            self.messages = messages
            return "Rendben."

    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    memory_store.remember_explicit(
        category="PROJECT",
        scope="USER",
        subject="LocalAI Desktop",
        key="preferred_remote_name",
        value="Prometheusz",
        source_chat_id="seed",
        source_excerpt="A Discord bot neve Prometheusz.",
    )

    ollama = FakeOllama()
    settings = DiscordBotSettings(
        extension_id="ext-memory-context",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=ollama,
        chat_store=ChatStore(tmp_path / "chats"),
        settings=settings,
        token="T" * 40,
        memory_store=memory_store,
    )

    answer, _chat_id = bridge._answer_prompt("Mit tudsz a LocalAI Desktop Prometheusz nevéről?")

    assert answer == "Rendben."
    system = ollama.messages[0]["content"]
    assert "LONG-TERM MEMORY CONTEXT:" in system
    assert "[PROJECT] LocalAI Desktop | preferred_remote_name: Prometheusz" in system


def test_compound_prometheusz_identity_and_memory_question_is_deterministic(tmp_path: Path):
    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("model must not be called for deterministic compound answer")

    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    memory_store.remember_explicit(
        category="USER_PROFILE",
        scope="USER",
        subject="Lilla",
        key="relationship_to_user",
        value="daughter",
        source_chat_id="seed",
        source_excerpt="Jegyezd meg, hogy Lilla a lányom.",
    )

    settings = DiscordBotSettings(
        extension_id="ext-compound",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=FailingOllama(),
        chat_store=ChatStore(tmp_path / "chats"),
        settings=settings,
        token="T" * 40,
        memory_store=memory_store,
    )

    answer, _chat_id = bridge._answer_prompt(
        "Itt vagy Prometheusz? Ki nekem Lilla?"
    )

    assert "Prometheusz a Discordos nevem" in answer
    assert "Lilla a lányod." in answer

