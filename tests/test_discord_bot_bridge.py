from pathlib import Path
from types import SimpleNamespace

import pytest

from app.artifact_service import ArtifactPlanItem, ArtifactRequest
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
    assert "same read-only grounded web research as the desktop" in system


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


def test_remote_web_request_uses_grounded_desktop_web_runtime(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

    calls = []

    def fake_web(client, model, messages, prompt):
        calls.append((client, model, messages, prompt))
        return (
            "Ellenőrzött termékszintű találatok:\n"
            "- Samsung 870 QVO 4TB — https://example.com/ssd\n\n"
            "Shopping evidence: PASS"
        )

    monkeypatch.setattr(bridge_module, "run_chat_web_request", fake_web)

    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("normal chat path must not handle explicit web requests")

    settings = DiscordBotSettings(
        extension_id="ext-web",
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
    )

    answer, chat_id = bridge._answer_prompt("Keress nekem 4 TB-os SSD-t")

    assert "Shopping evidence: PASS" in answer
    assert calls
    assert calls[0][1] == "qwen3-coder:30b"
    assert calls[0][3] == "Keress nekem 4 TB-os SSD-t"

    chat = bridge.chat_store.load(chat_id)
    assert chat["messages"][-1]["content"] == answer


def test_remote_non_web_prompt_stays_on_normal_local_model_path(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

    monkeypatch.setattr(
        bridge_module,
        "run_chat_web_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("web runtime must not run for ordinary chat")
        ),
    )

    class FakeOllama:
        def chat_once(self, model, messages):
            return "Normál helyi válasz."

    settings = DiscordBotSettings(
        extension_id="ext-chat",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=FakeOllama(),
        chat_store=ChatStore(tmp_path / "chats"),
        settings=settings,
        token="T" * 40,
    )

    answer, _chat_id = bridge._answer_prompt("Mondj egy rövid viccet.")

    assert answer == "Normál helyi válasz."



@pytest.mark.parametrize(
    ("artifact_format", "preset", "suffix"),
    [
        ("pdf", "Red Executive", ".pdf"),
        ("docx", "Red Executive", ".docx"),
        ("xlsx", "Red Executive Workbook", ".xlsx"),
        ("html", "Red Executive", ".html"),
        ("summary", "Local Summary", ".md"),
    ],
)
def test_remote_artifact_uses_memory_and_shared_artifact_service(
    tmp_path: Path,
    monkeypatch,
    artifact_format,
    preset,
    suffix,
):
    import app.discord_bot_bridge as bridge_module

    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError(
                "model must not be called when durable memory directly answers the artifact topic"
            )

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

    created = {}

    def fake_create_artifact(fmt, **kwargs):
        created["format"] = fmt
        created["kwargs"] = kwargs
        path = tmp_path / f"lilla{suffix}"
        path.write_bytes(b"artifact")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    settings = DiscordBotSettings(
        extension_id="ext-artifact",
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

    request = ArtifactRequest(format=artifact_format, preset=preset)
    answer, chat_id, artifact = bridge._create_remote_artifact(
        "Készíts fájlt arról, hogy ki nekem Lilla",
        request,
    )

    assert artifact.exists()
    assert created["format"] == artifact_format
    assert created["kwargs"]["preset"] == preset
    assert "Lilla a lányod." in created["kwargs"]["content"]
    assert artifact_format.upper() in answer

    chat = bridge.chat_store.load(chat_id)
    assert chat["messages"][-1]["role"] == "artifact"
    assert chat["messages"][-1]["content"] == str(artifact)
    assert chat["messages"][-1]["path"] == str(artifact)


def test_remote_xlsx_model_path_uses_excel_generation_contract(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

    class FakeOllama:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages):
            self.messages = messages
            return (
                '{"title":"SSD","sheets":[{"name":"Data",'
                '"headers":["Name"],"rows":[["Example"]]}]}'
            )

    ollama = FakeOllama()
    created = {}

    def fake_create_artifact(fmt, **kwargs):
        created["format"] = fmt
        created["kwargs"] = kwargs
        path = tmp_path / "result.xlsx"
        path.write_bytes(b"xlsx")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    settings = DiscordBotSettings(
        extension_id="ext-artifact-model",
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
    )

    request = ArtifactRequest(format="xlsx", preset="Red Executive Workbook")
    answer, _chat_id, artifact = bridge._create_remote_artifact(
        "Készíts Excel fájlt az SSD példákról",
        request,
    )

    assert artifact.exists()
    assert "XLSX" in answer
    assert created["format"] == "xlsx"
    assert created["kwargs"]["source_text"].startswith("Készíts Excel")
    assert "Return ONLY valid JSON" in ollama.messages[0]["content"]
    assert "host application will render" in ollama.messages[0]["content"]


def test_remote_document_model_path_uses_shared_render_instruction(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

    class FakeOllama:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages):
            self.messages = messages
            return "# Projekt riport\n\nRövid tartalom."

    ollama = FakeOllama()

    def fake_create_artifact(fmt, **kwargs):
        path = tmp_path / "project.docx"
        path.write_bytes(b"docx")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    settings = DiscordBotSettings(
        extension_id="ext-docx-model",
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
    )

    request = ArtifactRequest(format="docx", preset="Classic Executive")
    answer, _chat_id, artifact = bridge._create_remote_artifact(
        "Készíts Word dokumentumot a LocalAI Desktop projektről",
        request,
    )

    assert artifact.exists()
    assert "DOCX" in answer
    assert "host application will render" in ollama.messages[0]["content"]


def test_remote_multi_artifact_request_creates_every_file_once(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

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

    created = []

    def fake_create_artifact(fmt, **kwargs):
        created.append((fmt, kwargs))
        suffix = {
            "docx": ".docx",
            "xlsx": ".xlsx",
            "html": ".html",
            "summary": ".md",
        }[fmt]
        path = tmp_path / f"artifact_{len(created)}{suffix}"
        path.write_bytes(b"artifact")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("durable memory should answer all four artifact topics")

    settings = DiscordBotSettings(
        extension_id="ext-multi-artifact",
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

    plans = [
        ArtifactPlanItem(
            prompt="Készíts Word dokumentumot Red Executive stílusban arról, hogy ki nekem Lilla.",
            request=ArtifactRequest("docx", "Red Executive"),
        ),
        ArtifactPlanItem(
            prompt="Készíts Excel fájlt arról, hogy ki nekem Lilla.",
            request=ArtifactRequest("xlsx", "Red Executive Workbook"),
        ),
        ArtifactPlanItem(
            prompt="Készíts HTML riportot Classic Executive stílusban arról, hogy ki nekem Lilla.",
            request=ArtifactRequest("html", "Classic Executive"),
        ),
        ArtifactPlanItem(
            prompt="Készíts összefoglaló Markdown fájlt arról, hogy ki nekem Lilla.",
            request=ArtifactRequest("summary", "Local Summary"),
        ),
    ]
    original = "\n\n".join(item.prompt for item in plans)

    chat_id, results = bridge._create_remote_artifacts(original, plans)

    assert [fmt for fmt, _kwargs in created] == [
        "docx",
        "xlsx",
        "html",
        "summary",
    ]
    assert [kwargs["preset"] for _fmt, kwargs in created] == [
        "Red Executive",
        "Red Executive Workbook",
        "Classic Executive",
        "Local Summary",
    ]
    assert len(results) == 4
    assert all(path.exists() for _answer, path in results)
    assert all("Lilla a lányod." in kwargs["content"] for _fmt, kwargs in created)

    chat = bridge.chat_store.load(chat_id)
    user_messages = [
        item for item in chat["messages"]
        if item.get("role") == "user"
    ]
    artifacts = [
        item for item in chat["messages"]
        if item.get("role") == "artifact"
    ]
    assert user_messages[-1]["content"] == original
    assert len(user_messages) == 1
    assert len(artifacts) == 4


def test_prometheusz_executes_numbered_mixed_actions_in_order(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module
    from app.web_intent import plan_user_actions

    web_calls = []
    created = []

    def fake_web(client, model, messages, prompt):
        web_calls.append(prompt)
        if "Qwen" in prompt:
            return "WEB-QWEN: latest verified Qwen release."
        if "Ollama" in prompt:
            return (
                "WEB-OLLAMA: verified latest Ollama release is 9.9.9. "
                "Source: https://example.com/ollama"
            )
        raise AssertionError(prompt)

    monkeypatch.setattr(bridge_module, "run_chat_web_request", fake_web)

    def fake_create_artifact(fmt, **kwargs):
        created.append((fmt, kwargs))
        path = tmp_path / "ollama.html"
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    class FakeOllama:
        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages):
            self.calls.append(messages)
            user = messages[-1]["content"]
            if "TCP" in user:
                return "LOCAL-TCP: a TCP egy kapcsolatorientált protokoll."
            if "VERIFIED WEB RESEARCH SOURCE" in user:
                assert "verified latest Ollama release is 9.9.9" in user
                assert "use ONLY the VERIFIED WEB RESEARCH SOURCE" in messages[0]["content"]
                assert "Do not add release notes, features, changes" in messages[0]["content"]
                return "# Ollama riport\n\nA jelenlegi verzió: 9.9.9"
            raise AssertionError(user)

    ollama = FakeOllama()
    settings = DiscordBotSettings(
        extension_id="ext-mixed-actions",
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
    )

    prompt = """1. Melyik a jelenlegi legfrissebb Qwen verzió?

2. Magyarázd el röviden, mi az a TCP.

3. Mi a legújabb Ollama verzió, és készíts róla egy rövid HTML riportot."""

    results = [
        bridge._execute_planned_action(item.prompt, item.plan)
        for item in plan_user_actions(prompt)
    ]

    assert results[0]["messages"] == ["WEB-QWEN: latest verified Qwen release."]
    assert results[0]["artifacts"] == []

    assert results[1]["messages"] == [
        "LOCAL-TCP: a TCP egy kapcsolatorientált protokoll."
    ]
    assert results[1]["artifacts"] == []

    assert results[2]["messages"] == []
    assert len(results[2]["artifacts"]) == 1
    assert results[2]["artifacts"][0][1].suffix == ".html"

    assert web_calls == [
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
        "Mi a legújabb Ollama verzió, és készíts róla egy rövid HTML riportot.",
    ]
    assert created[0][0] == "html"
    assert "9.9.9" in created[0][1]["content"]
    assert "WEB-OLLAMA" in created[0][1]["source_text"]


def test_remote_artifact_with_web_context_does_not_use_stale_memory_shortcut(
    tmp_path: Path,
    monkeypatch,
):
    import app.discord_bot_bridge as bridge_module
    from app.web_intent import plan_user_action

    memory_store = MemoryStore(tmp_path / "memory.sqlite3")
    memory_store.remember_explicit(
        category="USER_PROFILE",
        scope="USER",
        subject="Ollama",
        key="current_version",
        value="0.1.37",
        source_chat_id="old",
        source_excerpt="Old version",
    )

    monkeypatch.setattr(
        bridge_module,
        "run_chat_web_request",
        lambda *args, **kwargs: (
            "Verified current Ollama version is 9.9.9. "
            "Source: https://example.com/ollama"
        ),
    )

    captured = {}

    def fake_create_artifact(fmt, **kwargs):
        captured.update(kwargs)
        path = tmp_path / "verified.html"
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    monkeypatch.setattr(bridge_module, "create_artifact", fake_create_artifact)

    class FakeOllama:
        def chat_once(self, model, messages):
            combined = "\n".join(item["content"] for item in messages)
            assert "Verified current Ollama version is 9.9.9" in combined
            return "# Verified\n\nOllama: 9.9.9"

    settings = DiscordBotSettings(
        extension_id="ext-grounded-artifact",
        name="Prometheusz",
        guild_id=111111111111111111,
        channel_id=222222222222222222,
        allowed_user_id=333333333333333333,
        model="qwen3-coder:30b",
    )
    bridge = DiscordBotBridge(
        ollama_client=FakeOllama(),
        chat_store=ChatStore(tmp_path / "chats"),
        settings=settings,
        token="T" * 40,
        memory_store=memory_store,
    )

    prompt = "Mi a legújabb Ollama verzió, és készíts róla HTML riportot."
    result = bridge._execute_planned_action(prompt, plan_user_action(prompt))

    assert len(result["artifacts"]) == 1
    assert "9.9.9" in captured["content"]
    assert "0.1.37" not in captured["content"]
    assert "use ONLY the VERIFIED WEB RESEARCH SOURCE" in captured.get(
        "source_text",
        "",
    ) or "Verified current Ollama version is 9.9.9" in captured.get(
        "source_text",
        "",
    )


def test_remote_crypto_quote_prefers_enabled_market_extension(tmp_path: Path, monkeypatch):
    import app.discord_bot_bridge as bridge_module

    class ExtensionStore:
        def find_by_preset_id(self, preset_id):
            assert preset_id == "crypto-market-data"
            return {
                "id": "market-ext",
                "enabled": True,
                "capabilities": ["crypto_quote", "crypto_ticker", "crypto_24h"],
                "config": {
                    "api_base_url": "https://api.exchange.coinbase.com",
                    "default_quote": "USD",
                },
            }

    monkeypatch.setattr(
        bridge_module,
        "run_crypto_market_request",
        lambda extension, prompt: (
            "A Bitcoin (BTC) aktuális ára: **81 632.88 USD**. "
            "Forrás: Coinbase Exchange public market data."
        ),
    )
    monkeypatch.setattr(
        bridge_module,
        "run_chat_web_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("web fallback must not run when market extension succeeds")
        ),
    )

    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("local model must not answer live crypto quote")

    settings = DiscordBotSettings(
        extension_id="ext-market",
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
        extension_store=ExtensionStore(),
    )

    answer, _chat_id = bridge._answer_prompt(
        "Mennyi most a bitcoin árfolyama?"
    )

    assert "81 632.88 USD" in answer
    assert "Coinbase Exchange public market data" in answer


def test_remote_crypto_quote_falls_back_to_grounded_web_on_market_error(
    tmp_path: Path,
    monkeypatch,
):
    import app.discord_bot_bridge as bridge_module

    class ExtensionStore:
        def find_by_preset_id(self, preset_id):
            return {
                "id": "market-ext",
                "enabled": True,
                "capabilities": ["crypto_quote"],
                "config": {},
            }

    monkeypatch.setattr(
        bridge_module,
        "run_crypto_market_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("market API unavailable")
        ),
    )
    monkeypatch.setattr(
        bridge_module,
        "run_chat_web_request",
        lambda client, model, messages, prompt: (
            "WEB FALLBACK: BTC/USD 81 600 USD."
        ),
    )

    class FailingOllama:
        def chat_once(self, model, messages):
            raise AssertionError("local model must not answer live crypto quote")

    settings = DiscordBotSettings(
        extension_id="ext-market-fallback",
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
        extension_store=ExtensionStore(),
    )

    answer, _chat_id = bridge._answer_prompt(
        "Mennyi most a bitcoin árfolyama?"
    )

    assert answer == "WEB FALLBACK: BTC/USD 81 600 USD."

