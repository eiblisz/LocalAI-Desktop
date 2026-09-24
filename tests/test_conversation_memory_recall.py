from copy import deepcopy
from types import MethodType, SimpleNamespace

from app import main_window as main_window_module
from app.action_runtime import ROUTE_CHAT
from app.conversation_memory_recall import (
    is_safe_direct_recall,
    resolve_current_conversation_recall,
)
from app.main_window import MainWindow
from app.memory_store import MemoryStore
from app.request_trace import RequestTrace
from app.task_constraints import build_task_constraints


def _state(value):
    return {
        "role": "user",
        "content": f"A tesztprojekt kódneve {value}.",
    }


def test_current_window_recall_returns_exact_explicit_user_value():
    result = resolve_current_conversation_recall(
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        messages=[_state("Kék Sárkány 7319")],
    )

    assert result.is_direct_hit is True
    assert result.answer == "Kék Sárkány 7319."
    assert result.source_kind == "recent_raw"


def test_current_window_recall_accepts_accentless_question():
    result = resolve_current_conversation_recall(
        "Mi a tesztprojekt kodneve ebben a beszelgetesben?",
        messages=[_state("Kék Sárkány 7319")],
    )

    assert result.answer == "Kék Sárkány 7319."


def test_current_window_recall_rejects_conflicting_values():
    result = resolve_current_conversation_recall(
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        messages=[_state("Kék Sárkány 7319"), _state("Vörös Sólyom 2024")],
    )

    assert result.is_direct_hit is False
    assert result.answer == ""
    assert result.candidate_count == 2


def test_current_window_recall_does_not_treat_index_metadata_as_fact():
    result = resolve_current_conversation_recall(
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        indexed_state=(
            "- User: topic=tesztprojekt; key=kódneve; "
            "scope=current_window"
        ),
    )

    assert result.is_direct_hit is False
    assert result.answer == ""


def test_current_window_recall_never_uses_another_chat_value():
    result = resolve_current_conversation_recall(
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        messages=[],
    )

    assert result.is_direct_hit is False
    assert result.retrieved_item_count == 0


def test_current_window_fast_path_keeps_language_script_validation():
    result = resolve_current_conversation_recall(
        "What is the project codename in this conversation?",
        messages=[{
            "role": "user",
            "content": "The project codename is 서울.",
        }],
    )

    assert result.is_direct_hit is True
    assert is_safe_direct_recall(
        "What is the project codename in this conversation?",
        result,
    ) is False


def test_desktop_current_window_recall_records_bounded_stages(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    host = SimpleNamespace(
        generation_chat_id="chat-a",
        pending_action_history_messages=[_state("Kék Sárkány 7319")],
        memory_store=store,
    )
    trace = RequestTrace("desktop")

    result = MainWindow._direct_conversation_memory_recall(
        host,
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        trace=trace,
    )

    snapshot = trace.snapshot()
    assert result.answer == "Kék Sárkány 7319."
    assert snapshot["metadata"]["memory_scope"] == "current_window"
    assert snapshot["metadata"]["current_window_hit"] is True
    assert {
        "memory_scope_resolution",
        "current_raw_context_retrieval",
        "window_memory_retrieval",
        "direct_memory_recall",
    }.issubset(snapshot["phases_ms"])


def test_desktop_fast_path_skips_worker_for_unambiguous_current_recall(
    tmp_path,
    monkeypatch,
):
    class ChatStore:
        def __init__(self, chat):
            self.chat = deepcopy(chat)

        def load(self, _chat_id):
            return deepcopy(self.chat)

        def save(self, chat):
            self.chat = deepcopy(chat)

    prompt = "Mi a tesztprojekt kódneve ebben a beszélgetésben?"
    chat = {"id": "chat-a", "messages": [_state("Kék Sárkány 7319")]}
    store = ChatStore(chat)
    contract = SimpleNamespace(
        index=0,
        prompt=prompt,
        route=ROUTE_CHAT,
        constraints=build_task_constraints(prompt),
        conversation_local=True,
        explicit_batch_child=False,
    )
    harness = SimpleNamespace(
        worker=None,
        thread=None,
        pending_action_contracts=[contract],
        pending_batch_trace=None,
        pending_action_batch_size=1,
        pending_action_model="gemma4:26b",
        generation_chat_id="chat-a",
        pending_action_history_messages=list(chat["messages"]),
        memory_store=MemoryStore(tmp_path / "memory.sqlite3"),
        store=store,
        current_chat=deepcopy(chat),
        status=SimpleNamespace(setText=lambda _value: None),
        _render_chat=lambda: None,
        _load_chat_list=lambda: None,
        _run_next_action_contract_safely=lambda: None,
    )
    harness._direct_conversation_memory_recall = MethodType(
        MainWindow._direct_conversation_memory_recall,
        harness,
    )
    harness._generation_target_chat = MethodType(
        MainWindow._generation_target_chat,
        harness,
    )
    monkeypatch.setattr(
        main_window_module.QTimer,
        "singleShot",
        lambda *_args, **_kwargs: None,
    )

    MainWindow._run_next_action_contract(harness)

    assistant = store.chat["messages"][-1]
    assert harness.worker is None
    assert assistant["content"] == "Kék Sárkány 7319."
    assert assistant["diagnostic"]["direct_memory_fast_path"] is True
    snapshot = harness.pending_request_trace.snapshot()
    assert snapshot["metadata"]["ollama_skipped"] is True
    assert snapshot["metadata"]["estimated_prompt_units"] == 0
