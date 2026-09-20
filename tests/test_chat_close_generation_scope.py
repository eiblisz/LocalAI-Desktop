from app.main_window import MainWindow


class _Store:
    def __init__(self):
        self.closed = []
        self.chats = {
            "chat-a": {"id": "chat-a", "title": "A", "closed": False},
            "chat-b": {"id": "chat-b", "title": "B", "closed": False},
        }

    def set_closed(self, chat_id, closed):
        self.closed.append((chat_id, closed))
        chat = dict(self.chats[chat_id])
        chat["closed"] = bool(closed)
        self.chats[chat_id] = chat
        return dict(chat)

    def list_chats(self):
        return [
            dict(chat)
            for chat in self.chats.values()
            if not chat.get("closed", False)
        ]

    def new_chat(self, _model):
        chat = {"id": "chat-new", "title": "New chat", "closed": False}
        self.chats["chat-new"] = chat
        return dict(chat)


class _ModelCombo:
    def currentText(self):
        return "qwen-test"


class _Window:
    def __init__(self):
        self.store = _Store()
        self.worker = object()
        self.generation_chat_id = "chat-a"
        self.current_chat = dict(self.store.chats["chat-b"])
        self.show_closed = False
        self.model_combo = _ModelCombo()
        self.loaded = False
        self.rendered = False

    def _load_chat_list(self):
        self.loaded = True

    def _render_chat(self):
        self.rendered = True


def test_other_chat_can_close_while_model_is_generating(monkeypatch):
    window = _Window()
    warnings = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    MainWindow._set_chat_closed(window, "chat-b", True)

    assert warnings == []
    assert ("chat-b", True) in window.store.closed
    assert window.loaded
    assert window.rendered
    assert window.current_chat["id"] == "chat-a"


def test_generating_chat_remains_protected_even_if_user_is_viewing_another_chat(
    monkeypatch,
):
    window = _Window()
    warnings = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    MainWindow._set_chat_closed(window, "chat-a", True)

    assert len(warnings) == 1
    assert window.store.closed == []
    assert window.current_chat["id"] == "chat-b"
