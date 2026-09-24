from app.action_runtime import ActionRuntime, ROUTE_CHAT, ROUTE_WEB
from app.chat_orchestration import normalize_web_mode, plan_chat_actions
from app.followup_resolution import resolve_contextual_followup


def test_common_orchestrator_preserves_web_modes():
    runtime = ActionRuntime()
    prompt = "Mikor írta Nimbus Szerző a Csillag Történetét?"

    auto = plan_chat_actions(runtime, prompt, web_mode="AUTO")
    on = plan_chat_actions(runtime, "Magyarázd el röviden a TCP-t.", web_mode="ON")
    off = plan_chat_actions(runtime, prompt, web_mode="OFF")

    assert auto[0].route == ROUTE_WEB
    assert auto[0].use_web is True
    assert on[0].route == ROUTE_CHAT
    assert on[0].use_web is False
    assert off[0].route == ROUTE_CHAT
    assert off[0].use_web is False


def test_factual_risk_is_generic_not_qa_entity_specific():
    runtime = ActionRuntime()

    contracts = plan_chat_actions(
        runtime,
        "Who wrote The Silver Observatory?",
        web_mode="AUTO",
    )

    assert contracts[0].route == ROUTE_WEB
    assert contracts[0].use_web is True


def test_creative_prompt_remains_local_in_auto():
    runtime = ActionRuntime()

    contracts = plan_chat_actions(
        runtime,
        "Írj egy rövid verset az őszi esőről.",
        web_mode="AUTO",
    )

    assert contracts[0].route == ROUTE_CHAT
    assert contracts[0].use_web is False


def test_conversation_local_state_statement_stays_local_with_web_on():
    contracts = plan_chat_actions(
        ActionRuntime(),
        (
            "Ebben a beszélgetésben a tesztprojekt kódneve "
            "Kék Sárkány 7319. Ezt később kérdezd vissza tőlem."
        ),
        web_mode="ON",
    )

    assert contracts[0].route == ROUTE_CHAT
    assert contracts[0].use_web is False
    assert contracts[0].conversation_local is True


def test_current_window_recall_stays_local_with_web_on():
    history = [{
        "role": "user",
        "content": "A tesztprojekt kódneve Kék Sárkány 7319.",
    }]

    contracts = plan_chat_actions(
        ActionRuntime(),
        "Mi a tesztprojekt kódneve ebben a beszélgetésben?",
        web_mode="ON",
        conversation_messages=history,
    )

    assert contracts[0].route == ROUTE_CHAT
    assert contracts[0].use_web is False
    assert contracts[0].conversation_local is True


def test_genuine_fresh_external_question_still_uses_web_with_web_on():
    contracts = plan_chat_actions(
        ActionRuntime(),
        "Melyik a jelenlegi legfrissebb Ollama verzió?",
        web_mode="ON",
    )

    assert contracts[0].route == ROUTE_WEB
    assert contracts[0].use_web is True


def test_external_chatgpt_and_historical_context_questions_are_not_local():
    history = [{"role": "user", "content": "Korábbi, nem kapcsolódó kérdés."}]
    prompts = (
        "What is the latest ChatGPT update?",
        "What is the historical context of the French Revolution?",
        "What happened before the French Revolution?",
    )

    for prompt in prompts:
        contracts = plan_chat_actions(
            ActionRuntime(),
            prompt,
            web_mode="ON",
            conversation_messages=history,
        )
        assert contracts[0].conversation_local is False


def test_mixed_batch_routes_recall_locally_and_fresh_query_to_web():
    prompt = (
        "Mi a kódnév, amit az előbb megadtam?\n"
        "Melyik a jelenlegi legfrissebb Ollama verzió?"
    )
    contracts = plan_chat_actions(
        ActionRuntime(),
        prompt,
        web_mode="ON",
        conversation_messages=[{
            "role": "user",
            "content": "A kódnév Kék Sárkány 7319.",
        }],
    )

    assert [contract.route for contract in contracts] == [ROUTE_CHAT, ROUTE_WEB]
    assert [contract.conversation_local for contract in contracts] == [True, False]


def test_invalid_mode_normalizes_to_auto():
    assert normalize_web_mode("weird") == "AUTO"


def test_multiline_questions_survive_followup_resolution_and_plan_independently():
    prompt = (
        "Ki James Hetfield?\n"
        "Mikor irta Arany Janos a Janos vitez cimu verset?\n"
        "Mikor alakult a Pokolgep zenekar?"
    )

    resolution = resolve_contextual_followup(prompt, [])

    assert resolution.resolved_intent == prompt
    assert resolution.resolved_intent.count("\n") == 2

    contracts = plan_chat_actions(
        ActionRuntime(),
        resolution.resolved_intent,
        web_mode="AUTO",
    )
    profiles = [
        contract.constraints.request_profile
        for contract in contracts
    ]

    assert len(contracts) == 3
    assert [
        (profile.requested_fact, profile.relation)
        for profile in profiles
    ] == [
        ("identity", "identity"),
        ("temporal", "authorship_creation"),
        ("temporal", "formation"),
    ]
    assert profiles[1].premise_check_required is True
