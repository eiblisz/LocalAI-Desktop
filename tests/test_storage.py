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


def test_title_is_bounded():
    text = "a" * 100
    title = ChatStore.infer_title(text)
    assert title.endswith("...")
    assert len(title) <= 45
