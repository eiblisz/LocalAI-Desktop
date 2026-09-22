from app.action_runtime import ActionRuntime, ROUTE_CHAT, ROUTE_WEB
from app.chat_orchestration import normalize_web_mode, plan_chat_actions


def test_common_orchestrator_preserves_web_modes():
    runtime = ActionRuntime()
    prompt = "Mikor írta Nimbus Szerző a Csillag Történetét?"

    auto = plan_chat_actions(runtime, prompt, web_mode="AUTO")
    on = plan_chat_actions(runtime, "Magyarázd el röviden a TCP-t.", web_mode="ON")
    off = plan_chat_actions(runtime, prompt, web_mode="OFF")

    assert auto[0].route == ROUTE_WEB
    assert auto[0].use_web is True
    assert on[0].route == ROUTE_WEB
    assert on[0].use_web is True
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


def test_invalid_mode_normalizes_to_auto():
    assert normalize_web_mode("weird") == "AUTO"
