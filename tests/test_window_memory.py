from app.memory_store import MemoryStore
from app.main_window import MainWindow
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
