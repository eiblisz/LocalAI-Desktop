from copy import deepcopy
from types import MethodType, SimpleNamespace

from app import main_window as main_window_module
from app.main_window import MainWindow
from app.request_trace import RequestTrace


class FakeLabel:
    def __init__(self):
        self.text = ""
        self.visible = False
        self.style = ""

    def setText(self, value):
        self.text = str(value)

    def setStyleSheet(self, value):
        self.style = str(value)

    def show(self):
        self.visible = True


class FakeStatus:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, value):
        self.text = str(value)

    def setToolTip(self, value):
        self.tooltip = str(value)


class FakeTimer:
    def __init__(self):
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


class FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeThread:
    def __init__(self):
        self.started = FakeSignal()
        self.finished = FakeSignal()
        self.deleted = False

    def start(self):
        pass

    def quit(self):
        pass

    def deleteLater(self):
        self.deleted = True


class FakeWorker:
    def __init__(self):
        self.token = FakeSignal()
        self.phase = FakeSignal()
        self.finished = FakeSignal()
        self.failed = FakeSignal()
        self.deleted = False

    def moveToThread(self, _thread):
        pass

    def run(self):
        pass

    def deleteLater(self):
        self.deleted = True


class FakeStore:
    def __init__(self, chats):
        self.chats = {
            chat_id: deepcopy(chat)
            for chat_id, chat in chats.items()
        }

    def load(self, chat_id):
        return deepcopy(self.chats[chat_id])

    def save(self, chat):
        self.chats[chat["id"]] = deepcopy(chat)


class FakeTrace:
    def __init__(self, total_ms):
        self.total_ms = float(total_ms)

    def snapshot(self):
        return {"total_ms": self.total_ms}


def _feedback_harness(total_ms=1250.0):
    harness = SimpleNamespace(
        thinking_base_text="",
        thinking_phase=0,
        thinking_label=FakeLabel(),
        thinking_timer=FakeTimer(),
        pending_action_model="gemma4:26b",
        pending_request_trace=FakeTrace(total_ms),
        status=FakeStatus(),
    )
    harness._pulse_thinking_indicator = MethodType(
        MainWindow._pulse_thinking_indicator,
        harness,
    )
    return harness


def test_request_feedback_is_visible_before_worker_phase_signal():
    harness = _feedback_harness(total_ms=120.0)

    MainWindow._start_thinking_indicator(
        harness,
        False,
        base_text="Útvonal kiválasztása",
    )

    assert harness.thinking_timer.active is True
    assert harness.thinking_label.visible is True
    assert harness.status.text == "Útvonal kiválasztása"
    assert "Útvonal kiválasztása" in harness.thinking_label.text
    assert "0.1 s" in harness.thinking_label.text


def test_worker_phase_updates_visible_status_and_real_elapsed_time():
    harness = _feedback_harness(total_ms=4700.0)
    harness._pulse_thinking_indicator = MethodType(
        MainWindow._pulse_thinking_indicator,
        harness,
    )

    MainWindow._on_execution_phase(harness, "Webes keresés")

    assert harness.status.text == "Webes keresés"
    assert harness.status.tooltip == ""
    assert harness.thinking_label.text == "Webes keresés… 4.7 s"


def test_first_worker_answer_chunk_renders_immediately():
    calls = []
    harness = SimpleNamespace(
        partial_assistant="",
        _render_streaming_chat=lambda: calls.append("render"),
    )

    MainWindow._on_token(harness, "Kész válasz")

    assert harness.partial_assistant == "Kész válasz"
    assert calls == ["render"]


def test_send_does_not_accept_new_message_while_thread_is_still_finishing():
    harness = SimpleNamespace(
        input=SimpleNamespace(toPlainText=lambda: "új kérdés"),
        worker=None,
        thread=object(),
        pending_action_contracts=[],
        status=FakeStatus(),
    )

    MainWindow._send(harness)

    assert harness.status.text == "Previous request is still finishing"


def _chat_contract(index, prompt):
    profile = SimpleNamespace(
        kind="direct_fact",
        requested_fact="identity" if index == 1 else "date",
        relation="",
    )
    return SimpleNamespace(
        index=index,
        prompt=prompt,
        route=main_window_module.ROUTE_CHAT,
        use_web=True,
        market_fallback=False,
        constraints=SimpleNamespace(request_profile=profile),
    )


def _batch_failure_harness(contracts):
    origin = {
        "id": "chat-origin",
        "title": "Acceptance",
        "messages": [{"role": "user", "content": "\n".join(
            contract.prompt for contract in contracts
        )}],
    }
    rendered = []
    loaded = []
    scheduled = []
    harness = SimpleNamespace(
        store=FakeStore({"chat-origin": origin}),
        current_chat=deepcopy(origin),
        generation_chat_id="chat-origin",
        worker=FakeWorker(),
        thread=FakeThread(),
        current_chat_uses_web=True,
        pending_action_contracts=list(contracts[1:]),
        active_action_contract=contracts[0],
        pending_action_model="qwen-test",
        pending_action_original_text="\n".join(
            contract.prompt for contract in contracts
        ),
        pending_action_context_suffix="",
        pending_action_images=[],
        pending_action_history_messages=[],
        pending_action_batch_size=len(contracts),
        pending_request_trace=RequestTrace("desktop"),
        partial_assistant="",
        web_mode="AUTO",
        client=object(),
        status=FakeStatus(),
        stop_button=FakeButton(),
        thinking_timer=FakeTimer(),
        expanded_diagnostic_message_ids=set(),
        _stop_thinking_indicator=lambda: None,
        _render_chat=lambda: rendered.append(True),
        _load_chat_list=lambda: loaded.append(True),
        _run_pending_scheduled_task=lambda: scheduled.append(True),
        _direct_user_memory_answer=lambda _prompt: "",
        _action_messages_for_model=lambda _prompt, _constraints: [],
        _crypto_market_extension=lambda: None,
        _multi_asset_market_extension=lambda: None,
        _on_token=lambda _token: None,
        _on_execution_phase=lambda _phase: None,
        _on_finished=lambda: None,
        _on_failed=lambda _message: None,
        _start_thinking_indicator=lambda _use_web: None,
    )
    harness.pending_request_trace.add_metadata(
        batch_size=len(contracts),
        child_index=contracts[0].index,
        child_status="running",
    )
    harness._cleanup_worker = MethodType(MainWindow._cleanup_worker, harness)
    harness._run_next_action_contract = MethodType(
        MainWindow._run_next_action_contract,
        harness,
    )
    return harness, rendered, loaded, scheduled


def test_failed_first_child_persists_diagnostic_and_batch_continues_in_order(
    monkeypatch,
):
    contracts = [
        _chat_contract(1, "Ki James Hetfield?"),
        _chat_contract(2, "Mikor irta Arany Janos a Janos vitez cimu verset?"),
        _chat_contract(3, "Mikor alakult a Pokolgep zenekar?"),
    ]
    harness, rendered, loaded, scheduled = _batch_failure_harness(contracts)
    started = [contracts[0].prompt]

    monkeypatch.setattr(main_window_module, "QThread", FakeThread)
    monkeypatch.setattr(
        main_window_module,
        "AdaptiveChatWorker",
        lambda _client, _model, _messages, prompt, **_kwargs: (
            started.append(prompt) or FakeWorker()
        ),
    )
    monkeypatch.setattr(
        main_window_module.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )

    class BlockingDialog:
        Critical = object()

        def __init__(self, *_args, **_kwargs):
            raise AssertionError("multi-question child failure opened a modal")

    monkeypatch.setattr(main_window_module, "QMessageBox", BlockingDialog)

    raw_failure = "provider token=secret-value no usable public sources"
    MainWindow._on_failed(harness, raw_failure)

    saved = harness.store.chats["chat-origin"]["messages"][-1]
    assert saved["role"] == "assistant"
    assert saved["content"].startswith("Most nem találtam")
    assert raw_failure not in saved["content"]
    assert saved["diagnostic"]["metadata"]["child_status"] == "failed"
    assert (
        saved["diagnostic"]["metadata"]["failure_code"]
        == "no_usable_public_sources"
    )
    assert (
        saved["diagnostic"]["metadata"]["diagnostic_failure"]
        == raw_failure
    )
    assert rendered == [True]
    assert loaded == [True]
    assert [contract.prompt for contract in harness.pending_action_contracts] == [
        contracts[1].prompt,
        contracts[2].prompt,
    ]
    assert harness.pending_action_batch_size == 3

    MainWindow._cleanup_worker(harness)
    assert started == [contracts[0].prompt, contracts[1].prompt]
    assert [contract.prompt for contract in harness.pending_action_contracts] == [
        contracts[2].prompt
    ]
    assert harness.generation_chat_id == "chat-origin"

    MainWindow._cleanup_worker(harness)
    assert started == [
        contracts[0].prompt,
        contracts[1].prompt,
        contracts[2].prompt,
    ]
    assert harness.pending_action_contracts == []
    assert harness.generation_chat_id == "chat-origin"

    MainWindow._cleanup_worker(harness)
    assert harness.pending_action_contracts == []
    assert harness.pending_action_batch_size == 0
    assert harness.generation_chat_id == ""
    assert harness.pending_request_trace is None
    assert scheduled == [True]

    harness.expanded_diagnostic_message_ids.add(saved["id"])
    diagnostic_html = MainWindow._diagnostic_html(harness, saved, 1)
    assert "Diagnosztika" in diagnostic_html
    assert "Status: failed" in diagnostic_html
    assert "Failure code: no_usable_public_sources" in diagnostic_html
    assert raw_failure not in diagnostic_html


def test_failed_child_is_saved_to_originating_chat_when_another_chat_is_open(
    monkeypatch,
):
    contract = _chat_contract(1, "Ki James Hetfield?")
    harness, rendered, _loaded, _scheduled = _batch_failure_harness([contract])
    other_chat = {"id": "chat-other", "title": "Other", "messages": []}
    harness.store.chats["chat-other"] = deepcopy(other_chat)
    harness.current_chat = deepcopy(other_chat)
    harness.pending_action_batch_size = 2

    class BlockingDialog:
        Critical = object()

        def __init__(self, *_args, **_kwargs):
            raise AssertionError("batch failure opened a modal")

    monkeypatch.setattr(main_window_module, "QMessageBox", BlockingDialog)

    MainWindow._on_failed(harness, "bounded child failure")

    assert len(harness.store.chats["chat-origin"]["messages"]) == 2
    assert harness.store.chats["chat-other"]["messages"] == []
    assert harness.current_chat["id"] == "chat-other"
    assert rendered == []


def test_single_request_failure_keeps_safe_error_dialog(monkeypatch):
    contract = _chat_contract(1, "Ki James Hetfield?")
    harness, _rendered, _loaded, _scheduled = _batch_failure_harness([contract])
    shown = []

    class RecordingDialog:
        Critical = "critical"

        def __init__(self, _parent):
            self.text = ""

        def setIcon(self, _icon):
            pass

        def setWindowTitle(self, _title):
            pass

        def setText(self, text):
            self.text = text

        def exec(self):
            shown.append(self.text)

    monkeypatch.setattr(main_window_module, "QMessageBox", RecordingDialog)

    MainWindow._on_failed(harness, "internal traceback and credentials")

    assert shown == ["A kérés feldolgozása most nem sikerült. Próbáld meg újra."]
    assert "internal traceback" not in shown[0]
