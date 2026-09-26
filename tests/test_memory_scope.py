from app.memory_scope import resolve_memory_context_scope


ACCEPTANCE_PROMPT = (
    "Írj egy részletes, legalább 10 bekezdéses magyar összefoglalót arról, "
    "hogyan működik a mesterséges intelligencia általánosságban, különös "
    "tekintettel a lokális modellek előnyei-hátrányai."
)


def test_fresh_general_knowledge_omits_all_runtime_memory_scopes():
    scope = resolve_memory_context_scope(ACCEPTANCE_PROMPT)

    assert scope.memory_scope == "fresh_general"
    assert scope.include_current_memory is False
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False
    assert scope.reason == "fresh_general"


def test_domain_overlap_without_user_reference_does_not_enable_global_memory():
    for prompt in (
        "Explain how local AI models work.",
        "What are the advantages of local models?",
        "How should Atlas Desktop be improved?",
    ):
        scope = resolve_memory_context_scope(prompt)

        assert scope.memory_scope == "fresh_general"
        assert scope.include_global_memory is False


def test_clear_user_project_reference_keeps_global_memory_eligible():
    for prompt in (
        "How should I improve my Atlas Desktop project?",
        "What model did I choose as default for my project?",
        "What do you remember about my Atlas project?",
    ):
        scope = resolve_memory_context_scope(prompt)

        assert scope.memory_scope == "relevant_memory"
        assert scope.include_global_memory is True


def test_explicit_durable_memory_request_keeps_global_memory_available():
    scope = resolve_memory_context_scope(
        "What is in global memory about my Atlas-7319 project?"
    )

    assert scope.memory_scope == "global_memory"
    assert scope.include_global_memory is True
    assert scope.include_cross_window is False
    assert scope.include_current_memory is False
    assert scope.reason == "explicit_global_memory"


def test_explicit_other_conversation_request_keeps_cross_window_available():
    scope = resolve_memory_context_scope(
        "What was the project codename in the other conversation?"
    )

    assert scope.memory_scope == "other_window"
    assert scope.include_cross_window is True
    assert scope.include_global_memory is False
    assert scope.include_current_memory is False
    assert scope.reason == "explicit_other_conversation"


def test_memory_architecture_feature_explanation_does_not_claim_current_context_scope():
    scope = resolve_memory_context_scope(
        (
            "Írj részletes összefoglalót a LocalAI Desktop memóriaarchitektúrájáról; "
            "térj ki a current chat contextre, Window Memoryra, Global Memoryra, "
            "cross-window retrievalre és a Remember ikonra."
        ),
        conversation_local=False,
    )

    assert scope.memory_scope == "fresh_general"
    assert scope.include_current_memory is False
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False
    assert scope.reason == "fresh_general"


def test_long_general_prompt_with_ordinary_deictic_pronoun_stays_fresh_general():
    scope = resolve_memory_context_scope(
        (
            "Írj egy részletes, 6–8 bekezdéses magyar esszét arról, hogyan működik "
            "az internet. Térj ki a DNS-re, TCP/IP-re, HTTP-re, HTTPS-re és arra is, "
            "mi történik technikailag attól a pillanattól, hogy beírok egy webcímet."
        ),
        conversation_local=False,
    )

    assert scope.memory_scope == "fresh_general"
    assert scope.include_current_memory is False
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False


def test_short_deictic_followup_still_uses_current_context():
    scope = resolve_memory_context_scope(
        "Mit gondolsz erről?",
        conversation_local=False,
    )

    assert scope.memory_scope == "current_context"
    assert scope.include_current_memory is True


def test_current_window_recall_scope_remains_available():
    scope = resolve_memory_context_scope(
        "What did I say in this conversation?",
        conversation_local=True,
    )

    assert scope.memory_scope == "current_window"
    assert scope.include_current_memory is True
    assert scope.include_cross_window is False
    assert scope.include_global_memory is False
    assert scope.reason == "current_window_context"
