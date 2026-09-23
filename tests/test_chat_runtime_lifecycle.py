from copy import deepcopy
from types import MethodType, SimpleNamespace

from app import main_window as main_window_module
from app.action_runtime import ActionRuntime
from app.main_window import MainWindow
from app.request_trace import RequestTrace
from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    QThread,
    QTimer,
    Signal,
    Slot,
)


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


def test_multiline_send_sets_batch_size_and_child_failure_stays_nonblocking(
    monkeypatch,
):
    prompt = (
        "Ki James Hetfield?\n"
        "Mikor irta Arany Janos a Janos vitez cimu verset?\n"
        "Mikor alakult a Pokolgep zenekar?"
    )
    chat = {
        "id": "chat-origin",
        "title": "Acceptance",
        "messages": [],
        "closed": False,
    }
    cleared = []
    rendered = []
    loaded = []
    harness = SimpleNamespace(
        input=SimpleNamespace(
            toPlainText=lambda: prompt,
            clear=lambda: cleared.append(True),
        ),
        model_combo=SimpleNamespace(currentText=lambda: "qwen-test"),
        worker=None,
        thread=None,
        pending_action_contracts=[],
        pending_action_batch_size=0,
        current_chat=deepcopy(chat),
        store=FakeStore({"chat-origin": chat}),
        attachment_context=[],
        action_runtime=ActionRuntime(),
        web_mode="AUTO",
        pending_request_trace=None,
        generation_chat_id="",
        current_chat_uses_web=True,
        status=FakeStatus(),
        stop_button=FakeButton(),
        _crypto_market_extension=lambda: None,
        _multi_asset_market_extension=lambda: None,
        _start_thinking_indicator=lambda *_args, **_kwargs: None,
        _stop_thinking_indicator=lambda: None,
        _load_chat_list=lambda: loaded.append(True),
        _render_chat=lambda: rendered.append(True),
        _run_next_action_contract=lambda: None,
    )
    harness._generation_target_chat = MethodType(
        MainWindow._generation_target_chat,
        harness,
    )

    class BlockingDialog:
        Critical = object()

        def __init__(self, *_args, **_kwargs):
            raise AssertionError("multi-question child failure opened a modal")

    monkeypatch.setattr(main_window_module, "QMessageBox", BlockingDialog)

    MainWindow._send(harness)

    assert harness.pending_action_batch_size == 3
    assert len(harness.pending_action_contracts) == 3
    assert cleared == [True]

    MainWindow._on_failed(harness, "provider timeout")

    saved = harness.store.chats["chat-origin"]["messages"]
    assert [message["role"] for message in saved] == ["user", "assistant"]
    assert saved[-1]["diagnostic"]["metadata"]["child_status"] == "failed"


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
        "messages": [{
            "role": "user",
            "content": "\n".join(contract.prompt for contract in contracts),
        }],
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
        pending_batch_trace=RequestTrace("desktop"),
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
    harness._generation_target_chat = MethodType(
        MainWindow._generation_target_chat,
        harness,
    )
    harness._run_next_action_contract = MethodType(
        MainWindow._run_next_action_contract,
        harness,
    )
    harness._run_next_action_contract_safely = MethodType(
        MainWindow._run_next_action_contract_safely,
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

    raw_failure = "provider timeout no usable public sources"
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


def test_failed_child_never_falls_back_to_an_unrelated_open_chat(
    monkeypatch,
):
    contract = _chat_contract(1, "Ki James Hetfield?")
    harness, rendered, _loaded, _scheduled = _batch_failure_harness([contract])
    other_chat = {"id": "chat-other", "title": "Other", "messages": []}
    harness.current_chat = deepcopy(other_chat)
    harness.pending_action_batch_size = 2
    harness.store.load = lambda _chat_id: (_ for _ in ()).throw(OSError("read"))

    class BlockingDialog:
        Critical = object()

        def __init__(self, *_args, **_kwargs):
            raise AssertionError("batch failure opened a modal")

    monkeypatch.setattr(main_window_module, "QMessageBox", BlockingDialog)

    MainWindow._on_failed(harness, "bounded child failure")

    assert harness.current_chat == other_chat
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


def test_memory_child_failure_uses_same_safe_nonblocking_batch_result(
    monkeypatch,
):
    contract = _chat_contract(1, "Jegyezd meg, hogy a kedvenc színem a kék.")
    harness, _rendered, _loaded, _scheduled = _batch_failure_harness([contract])
    harness.pending_action_batch_size = 2
    harness._on_failed = MethodType(MainWindow._on_failed, harness)

    class BlockingDialog:
        Critical = object()

        def __init__(self, *_args, **_kwargs):
            raise AssertionError("memory child failure opened a modal")

    monkeypatch.setattr(main_window_module, "QMessageBox", BlockingDialog)

    MainWindow._on_memory_failed(harness, "database connection details")

    saved = harness.store.chats["chat-origin"]["messages"][-1]
    assert harness.status.text == "Memory save failed"
    assert saved["content"] == (
        "A kérés feldolgozása most nem sikerült. Próbáld meg újra."
    )
    assert saved["diagnostic"]["metadata"]["child_status"] == "failed"
    assert saved["diagnostic"]["metadata"]["failure_code"] == "execution_failed"
    assert "database connection details" not in saved["content"]


class EventLoopWorker(QObject):
    token = Signal(str)
    phase = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, prompt, runtime_failures):
        super().__init__()
        self.prompt = prompt
        self.runtime_failures = runtime_failures
        self.source_metadata = []
        self.diagnostic_metadata = {}

    @Slot()
    def run(self):
        if self.prompt in self.runtime_failures:
            self.failed.emit(self.runtime_failures[self.prompt])
            return
        self.token.emit(f"answer:{self.prompt}")
        self.finished.emit()

    def stop(self):
        pass


def _run_qt_batch(monkeypatch, contracts, *, runtime_failures=None, start_failures=()):
    app = QCoreApplication.instance() or QCoreApplication([])
    loop = QEventLoop()
    base_harness, _rendered, _loaded, scheduled = _batch_failure_harness(
        contracts
    )
    harness = QObject()
    harness.__dict__.update(base_harness.__dict__)
    harness._cleanup_worker = MethodType(MainWindow._cleanup_worker, harness)
    harness._generation_target_chat = MethodType(
        MainWindow._generation_target_chat,
        harness,
    )
    harness._run_next_action_contract = MethodType(
        MainWindow._run_next_action_contract,
        harness,
    )
    harness._run_next_action_contract_safely = MethodType(
        MainWindow._run_next_action_contract_safely,
        harness,
    )
    harness.worker = None
    harness.thread = None
    harness.partial_assistant = ""
    harness._on_token = MethodType(MainWindow._on_token, harness)
    harness._on_finished = MethodType(MainWindow._on_finished, harness)
    harness._on_failed = MethodType(MainWindow._on_failed, harness)
    harness._render_streaming_chat = lambda: None
    harness._start_thinking_indicator = lambda *_args, **_kwargs: None
    harness.pending_action_contracts = list(contracts)
    harness.active_action_contract = None

    started = []
    runtime_failures = dict(runtime_failures or {})

    def worker_factory(_client, _model, _messages, prompt, **_kwargs):
        started.append(prompt)
        if prompt in start_failures:
            raise RuntimeError(f"start failed: {prompt}")
        return EventLoopWorker(prompt, runtime_failures)

    monkeypatch.setattr(main_window_module, "QThread", QThread)
    monkeypatch.setattr(
        main_window_module,
        "AdaptiveChatWorker",
        worker_factory,
    )

    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)

    def stop_when_drained():
        if (
            not harness.pending_action_contracts
            and harness.worker is None
            and harness.thread is None
            and not harness.generation_chat_id
        ):
            timeout.stop()
            loop.quit()
            return
        QTimer.singleShot(5, stop_when_drained)

    timeout.start(3000)
    QTimer.singleShot(0, harness._run_next_action_contract_safely)
    QTimer.singleShot(5, stop_when_drained)
    loop.exec()
    assert not timeout.isActive(), "Qt event loop timed out before the batch drained"
    return harness, started, scheduled


def test_real_qt_event_loop_runtime_failure_continues_and_drains(monkeypatch):
    contracts = [
        _chat_contract(0, "Q1"),
        _chat_contract(1, "Q2"),
        _chat_contract(2, "Q3"),
    ]

    harness, started, scheduled = _run_qt_batch(
        monkeypatch,
        contracts,
        runtime_failures={"Q1": "evidence guard rejected the result"},
    )

    assert started == ["Q1", "Q2", "Q3"]
    assert harness.pending_action_contracts == []
    assert scheduled == [True]
    messages = harness.store.chats["chat-origin"]["messages"]
    failure = next(item for item in messages if item.get("diagnostic"))
    assert failure["diagnostic"]["metadata"]["child_status"] == "failed"
    assert failure["diagnostic"]["metadata"]["child_index"] == 0
    assert failure["diagnostic"]["child_trace_id"]
    assert failure["diagnostic"]["batch_trace_id"]
    assert failure["diagnostic"]["build_sha"]


def test_real_qt_event_loop_start_failure_continues_to_next_child(monkeypatch):
    contracts = [
        _chat_contract(0, "Q1"),
        _chat_contract(1, "Q2"),
        _chat_contract(2, "Q3"),
    ]

    harness, started, scheduled = _run_qt_batch(
        monkeypatch,
        contracts,
        start_failures={"Q2"},
    )

    assert started == ["Q1", "Q2", "Q3"]
    assert harness.pending_action_contracts == []
    assert scheduled == [True]
    failures = [
        item for item in harness.store.chats["chat-origin"]["messages"]
        if item.get("diagnostic")
    ]
    assert [
        item["diagnostic"]["metadata"].get("diagnostic_failure")
        for item in failures
    ] == ["start failed: Q2"]
    assert len(failures) == 1
    assert failures[0]["diagnostic"]["metadata"]["child_index"] == 1
    assert failures[0]["diagnostic"]["metadata"]["failure_phase"] == "child_start"
