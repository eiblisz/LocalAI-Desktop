from types import SimpleNamespace

from app.main_window import MainWindow
from app.memory_store import MemoryStore


def _build_context(store, query):
    host = SimpleNamespace(memory_store=store)
    return MainWindow._build_memory_context(host, query)


def test_runtime_memory_context_includes_relevant_canonical_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    store.add_memory(
        category="PROJECT",
        scope="global",
        subject="QuantAI",
        key="primary_asset",
        value="BTCUSDT 15m realistic",
        importance="REMEMBER",
    )
    store.add_memory(
        category="PREFERENCE",
        scope="global",
        subject="Interface",
        key="theme",
        value="dark desktop",
        importance="REMEMBER",
    )

    context = _build_context(store, "Tell me about my BTCUSDT project")

    assert "LONG-TERM MEMORY CONTEXT:" in context
    assert "BTCUSDT 15m realistic" in context
    assert 'topic="QuantAI"' in context
    assert 'relation="primary asset"' in context
    assert "never quote as answer" in context
    assert "dark desktop" not in context


def test_runtime_memory_context_excludes_irrelevant_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    store.add_memory(
        category="PREFERENCE",
        scope="global",
        subject="Interface",
        key="theme",
        value="dark desktop",
        importance="REMEMBER",
    )

    context = _build_context(store, "Explain Python decorators")

    assert context == ""


def test_runtime_memory_context_excludes_session_only_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    store.add_memory(
        category="WORKING",
        scope="global",
        subject="Temporary",
        key="experiment",
        value="BTCUSDT temporary test",
        importance="SESSION_ONLY",
    )

    context = _build_context(store, "What is the BTCUSDT temporary test?")

    assert context == ""


def test_runtime_memory_context_excludes_unrelated_pinned_global_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")

    store.add_memory(
        category="RULE",
        scope="global",
        subject="Communication",
        key="command_format",
        value="Prefer single-line PowerShell commands",
        importance="PINNED",
    )

    context = _build_context(store, "Tell me something unrelated")

    assert context == ""
