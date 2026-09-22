from types import MethodType, SimpleNamespace

from app.main_window import MainWindow


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
