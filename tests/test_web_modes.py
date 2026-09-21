from app.action_runtime import (
    ROUTE_ARTIFACT,
    ROUTE_CHAT,
    ROUTE_WEB,
    ActionRuntime,
)


def test_web_auto_routes_current_request_to_web_and_stable_request_local():
    runtime = ActionRuntime()

    current = runtime.plan_many("Mi a jelenlegi Ollama verzio?")
    stable = runtime.plan_many("Magyarazd el roviden, mi az a TCP.")

    assert current[0].route == ROUTE_WEB
    assert current[0].use_web is True
    assert stable[0].route == ROUTE_CHAT
    assert stable[0].use_web is False


def test_web_on_forces_stable_chat_to_web():
    runtime = ActionRuntime()

    contracts = runtime.plan_many(
        "Magyarazd el roviden, mi az a TCP.",
        force_web=True,
    )

    assert contracts[0].route == ROUTE_WEB
    assert contracts[0].use_web is True


def test_web_off_forces_explicit_search_request_to_local_chat():
    runtime = ActionRuntime()

    contracts = runtime.plan_many(
        "Keress ra a weben a legfrissebb Qwen modellre.",
        disable_web=True,
    )

    assert contracts[0].route == ROUTE_CHAT
    assert contracts[0].use_web is False
    assert "external_read" not in contracts[0].required_authorities


def test_web_off_keeps_artifact_creation_local_without_web_grounding():
    runtime = ActionRuntime()

    contracts = runtime.plan_many(
        "Mi a legfrissebb Ollama verzio, es keszits rola HTML riportot.",
        disable_web=True,
    )

    assert contracts[0].route == ROUTE_ARTIFACT
    assert contracts[0].use_web is False
    assert "external_read" not in contracts[0].required_authorities
