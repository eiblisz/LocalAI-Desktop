from app.memory_scope import resolve_memory_context_scope


def test_fresh_general_knowledge_omits_all_runtime_memory_scopes():
    scope = resolve_memory_context_scope(
        "Adj egy altalanos, tiz bekezdeses magyarazatot az AI-rol."
    )

    assert scope.memory_scope == "fresh_general"
    assert scope.include_current_memory is False
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False


def test_explicit_durable_memory_request_keeps_global_memory_available():
    scope = resolve_memory_context_scope(
        "What is in global memory about my Atlas-7319 project?"
    )

    assert scope.memory_scope == "global_memory"
    assert scope.include_global_memory is True
    assert scope.include_cross_window is False
    assert scope.include_current_memory is False


def test_explicit_other_conversation_request_keeps_cross_window_available():
    scope = resolve_memory_context_scope(
        "What was the project codename in the other conversation?"
    )

    assert scope.memory_scope == "other_window"
    assert scope.include_cross_window is True
    assert scope.include_global_memory is False
    assert scope.include_current_memory is False


def test_current_window_recall_scope_remains_available():
    scope = resolve_memory_context_scope(
        "What did I say in this conversation?",
        conversation_local=True,
    )

    assert scope.memory_scope == "current_window"
    assert scope.include_current_memory is True
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False
