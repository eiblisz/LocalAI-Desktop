from pathlib import Path

from app.storage import ChatStore


def test_new_chat_and_roundtrip(tmp_path: Path):
    store = ChatStore(tmp_path)
    chat = store.new_chat("example-model")
    chat["messages"].append({"role": "user", "content": "hello"})
    store.save(chat)

    loaded = store.load(chat["id"])

    assert loaded["model"] == "example-model"
    assert loaded["messages"][0]["content"] == "hello"
    assert loaded["pinned"] is False
    assert loaded["closed"] is False


def test_title_is_bounded():
    text = "a" * 100
    title = ChatStore.infer_title(text)
    assert title.endswith("...")
    assert len(title) <= 45


def test_rename_pin_and_close(tmp_path: Path):
    store = ChatStore(tmp_path)
    chat = store.new_chat("model")

    renamed = store.rename(chat["id"], "My important chat")
    assert renamed["title"] == "My important chat"

    pinned = store.set_pinned(chat["id"], True)
    assert pinned["pinned"] is True

    closed = store.set_closed(chat["id"], True)
    assert closed["closed"] is True
    assert store.list_chats() == []

    closed_items = store.list_chats(include_closed=True)
    assert len(closed_items) == 1
    assert closed_items[0]["id"] == chat["id"]


def test_pinned_chats_sort_before_unpinned(tmp_path: Path):
    store = ChatStore(tmp_path)
    first = store.new_chat("model")
    second = store.new_chat("model")
    store.rename(first["id"], "Pinned")
    store.rename(second["id"], "Normal")
    store.set_pinned(first["id"], True)

    chats = store.list_chats()
    assert chats[0]["id"] == first["id"]
