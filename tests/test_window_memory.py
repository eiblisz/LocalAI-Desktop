from types import SimpleNamespace

from app.memory_store import MemoryStore
from app.main_window import MainWindow
from app.action_runtime import ActionRuntime, ROUTE_CHAT
from app.chat_orchestration import plan_chat_actions
from app.storage import ChatStore
from app.window_memory import RECENT_MESSAGE_LIMIT, WindowMemoryService


def _conversation(turns):
    messages = []
    for index in range(turns):
        messages.extend([
            {"role": "user", "content": f"Task state {index}: requirement alpha."},
            {"role": "assistant", "content": f"Result {index}: completed successfully."},
        ])
    return messages


def _desktop_messages(store, service, chat_id, history, prompt, *, local):
    host = SimpleNamespace(
        memory_store=store,
        window_memory=service,
        generation_chat_id=chat_id,
        pending_action_history_messages=list(history),
        pending_request_trace=None,
        pending_action_original_text=prompt,
        pending_action_context_suffix="",
        pending_action_images=[],
    )
    host._build_memory_context = lambda query: MainWindow._build_memory_context(
        host,
        query,
    )
    return MainWindow._action_messages_for_model(
        host,
        prompt,
        conversation_local=local,
    )


def test_window_memory_persists_and_is_isolated(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    store.upsert_window_memory(
        "chat-a",
        "- User: Project Alpha uses SQLite.",
        compacted_message_count=4,
        source_message_count=16,
    )
    store.upsert_window_memory(
        "chat-b",
        "- User: Project Beta uses JSON.",
        compacted_message_count=2,
        source_message_count=14,
    )

    reloaded = MemoryStore(path)
    assert "Alpha" in reloaded.get_window_memory("chat-a")["summary"]
    assert "Beta" not in reloaded.get_window_memory("chat-a")["summary"]
    assert "Beta" in reloaded.get_window_memory("chat-b")["summary"]


def test_model_switch_does_not_change_window_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    service = WindowMemoryService(store)
    messages = _conversation(8)

    qwen_context = service.prepare_context("chat-a", messages, "alpha")
    gemma_context = service.prepare_context("chat-a", messages, "alpha")

    assert qwen_context.summary == gemma_context.summary
    assert store.get_window_memory("chat-a")["chat_id"] == "chat-a"


def test_model_switch_recall_routes_to_same_persisted_window_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-a",
        "- User: A tesztprojekt kódneve Kék Sárkány 7319.",
        compacted_message_count=4,
        source_message_count=16,
    )
    summary = store.get_window_memory("chat-a")["summary"]

    qwen = plan_chat_actions(
        ActionRuntime(),
        "Mi a kódnév, amit az előbb megadtam?",
        web_mode="ON",
        window_memory=summary,
    )
    gemma = plan_chat_actions(
        ActionRuntime(),
        "Mi a kódnév, amit az előbb megadtam?",
        web_mode="ON",
        window_memory=summary,
    )

    assert qwen[0].route == gemma[0].route == ROUTE_CHAT
    assert qwen[0].conversation_local is gemma[0].conversation_local is True


def test_conversation_local_recall_does_not_load_other_window_summary(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-a",
        "- User: A tesztprojekt kódneve Kék Sárkány 7319.",
        compacted_message_count=4,
        source_message_count=16,
    )
    service = WindowMemoryService(store)

    unrelated = service.prepare_context(
        "chat-b",
        [],
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        include_related_windows=False,
    )

    assert unrelated.summary == ""
    assert unrelated.global_windows == []
    assert "Kék Sárkány 7319" not in service.context_text(unrelated)


def test_current_conversation_recall_excludes_other_windows_and_global_metadata(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-a",
        "- User: A tesztprojekt kódneve Kék Sárkány 7319.",
        compacted_message_count=4,
        source_message_count=16,
    )
    store.add_memory(
        category="PROJECT",
        scope="GLOBAL",
        subject="Economic_History",
        key="preferred_test_color",
        value="A teszt színe green",
        importance="REMEMBER",
    )
    service = WindowMemoryService(store)
    prompt = "Mi a tesztprojekt kódneve ebben a beszélgetésben?"

    messages = _desktop_messages(
        store,
        service,
        "chat-b",
        [],
        prompt,
        local=True,
    )
    serialized = "\n".join(str(item.get("content") or "") for item in messages)

    assert "CURRENT CONVERSATION AUTHORITY:" in serialized
    assert "Kék Sárkány 7319" not in serialized
    assert "Economic_History" not in serialized
    assert "preferred_test_color" not in serialized
    assert "green" not in serialized


def test_current_conversation_recall_keeps_its_own_window_value(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-a",
        "- User: A tesztprojekt kódneve Kék Sárkány 7319.",
        compacted_message_count=4,
        source_message_count=16,
    )
    service = WindowMemoryService(store)
    prompt = "Mi a tesztprojekt kódneve ebben a beszélgetésben?"

    messages = _desktop_messages(
        store,
        service,
        "chat-a",
        [],
        prompt,
        local=True,
    )

    assert "Kék Sárkány 7319" in messages[0]["content"]


def test_explicit_other_window_recall_can_use_bounded_related_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-a",
        "- User: A tesztprojekt kódneve Kék Sárkány 7319.",
        compacted_message_count=4,
        source_message_count=16,
    )
    service = WindowMemoryService(store)
    prompt = "Mi volt a másik beszélgetésben megadott tesztprojekt kódneve?"
    contracts = plan_chat_actions(ActionRuntime(), prompt, web_mode="ON")

    messages = _desktop_messages(
        store,
        service,
        "chat-b",
        [],
        prompt,
        local=contracts[0].conversation_local,
    )

    assert contracts[0].conversation_local is False
    assert "RELATED WINDOW MEMORY:" in messages[0]["content"]
    assert "Kék Sárkány 7319" in messages[0]["content"]


def test_explicit_long_term_memory_query_keeps_global_memory_available(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add_memory(
        category="PROJECT",
        scope="GLOBAL",
        subject="Economic_History",
        key="preferred_test_color",
        value="A teszt színe green",
        importance="REMEMBER",
    )
    service = WindowMemoryService(store)
    prompt = "Mi van a hosszú távú memóriában a teszt színéről?"
    contracts = plan_chat_actions(ActionRuntime(), prompt, web_mode="ON")

    messages = _desktop_messages(
        store,
        service,
        "chat-b",
        [],
        prompt,
        local=contracts[0].conversation_local,
    )
    system = messages[0]["content"]

    assert contracts[0].conversation_local is False
    assert "LONG-TERM MEMORY CONTEXT:" in system
    assert "Durable memory value: A teszt színe green" in system
    assert 'topic="Economic_History"' in system
    assert 'relation="preferred test color"' in system


def test_global_recall_wording_uses_durable_memory_scope():
    english = plan_chat_actions(
        ActionRuntime(),
        "What do you remember globally about my project?",
        web_mode="ON",
    )
    hungarian = plan_chat_actions(
        ActionRuntime(),
        "Mire emlékszel globálisan a projektemről?",
        web_mode="ON",
    )

    assert english[0].conversation_local is False
    assert hungarian[0].conversation_local is False


def test_long_chat_compacts_old_messages_and_keeps_recent_raw_context(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    service = WindowMemoryService(store)
    messages = _conversation(10)

    context = service.prepare_context("chat-a", messages, "requirement alpha")

    assert context.compacted is True
    assert "Task state 0" in context.summary
    assert len(context.recent_messages) == RECENT_MESSAGE_LIMIT
    assert context.recent_messages[-1]["content"].startswith("Result 9")
    assert store.list_memories() == []


def test_first_message_over_recent_limit_is_compacted_without_blind_spot(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    service = WindowMemoryService(store)
    messages = _conversation(6) + [
        {"role": "user", "content": "The thirteenth message must remain visible."}
    ]

    context = service.prepare_context("chat-a", messages, "thirteenth")

    assert context.compacted is True
    assert "Task state 0" in context.summary
    assert len(context.recent_messages) == RECENT_MESSAGE_LIMIT


def test_empty_compaction_delta_is_not_silently_dropped(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    service = WindowMemoryService(store)
    messages = [
        {"role": "user", "content": "", "images": [f"image-{index}"]}
        for index in range(13)
    ]

    context = service.prepare_context("chat-a", messages, "image")

    assert context.summary == ""
    assert len(context.recent_messages) == 13


def test_window_registry_excludes_secret_bearing_summaries(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-secret",
        "- User: alpha project password is do-not-share.",
        compacted_message_count=2,
        source_message_count=14,
    )
    store.upsert_window_memory(
        "chat-safe",
        "- User: alpha project uses SQLite.",
        compacted_message_count=2,
        source_message_count=14,
    )

    matches = store.search_window_memories("alpha project password", limit=5)

    assert [item["chat_id"] for item in matches] == ["chat-safe"]


def test_window_registry_tokenizes_accented_hungarian_words(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert_window_memory(
        "chat-hu",
        "- User: árvíztűrő projekt állapota kész.",
        compacted_message_count=2,
        source_message_count=14,
    )

    matches = store.search_window_memories("árvíztűrő projekt", limit=2)

    assert [item["chat_id"] for item in matches] == ["chat-hu"]


def test_cross_window_registry_is_bounded_and_summary_only(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    for index in range(8):
        store.upsert_window_memory(
            f"chat-{index}",
            f"- User: shared alpha project state {index}.",
            compacted_message_count=2,
            source_message_count=14,
        )

    matches = store.search_window_memories(
        "alpha project state",
        exclude_chat_id="chat-0",
        limit=2,
    )

    assert len(matches) == 2
    assert all(set(item) == {
        "chat_id",
        "summary",
        "compacted_message_count",
        "source_message_count",
        "created_at",
        "updated_at",
    } for item in matches)
    assert all(item["chat_id"] != "chat-0" for item in matches)


def test_thumbs_up_persists_without_creating_global_memory(tmp_path):
    path = tmp_path / "memory.sqlite3"
    store = MemoryStore(path)
    store.set_response_feedback("chat-a", "message-a", "thumbs_up")

    reloaded = MemoryStore(path)
    assert reloaded.get_response_feedback("chat-a", "message-a") == {
        "thumbs_up": True
    }
    assert reloaded.list_memories() == []


def test_chat_rename_keeps_stable_window_memory_link(tmp_path):
    chats = ChatStore(tmp_path / "chats")
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    chat = chats.new_chat("qwen")
    memory.upsert_window_memory(
        chat["id"],
        "- User: stable state.",
        compacted_message_count=2,
        source_message_count=14,
    )

    chats.rename(chat["id"], "Renamed")

    assert chats.load(chat["id"])["id"] == chat["id"]
    assert memory.get_window_memory(chat["id"])["summary"] == "- User: stable state."


def test_assistant_response_renders_distinct_feedback_and_remember_actions(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    host = type("Host", (), {})()
    host.memory_store = store
    host.current_chat = {
        "id": "chat-a",
        "messages": [{"id": "message-a", "role": "assistant", "content": "Useful."}],
    }

    rendered = MainWindow._response_actions_html(
        host,
        host.current_chat["messages"][0],
        0,
    )

    assert "localai-feedback://thumbs_up/0" in rendered
    assert "localai-feedback://remember/0" in rendered
    assert "👍" in rendered
    assert "🧠" in rendered
