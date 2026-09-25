from app.action_runtime import (
    AUTH_ARTIFACT_CREATE,
    AUTH_EXTERNAL_READ,
    AUTH_LOCAL_MODEL,
    AUTH_MEMORY_WRITE,
    ROUTE_ARTIFACT,
    ROUTE_CHAT,
    ROUTE_CRYPTO_MARKET,
    ROUTE_MARKET_WEB,
    ROUTE_MEMORY_WRITE,
    ROUTE_MULTI_ASSET_MARKET,
    ROUTE_WEB,
    ActionRuntime,
)


def test_action_runtime_routes_normal_chat_locally():
    decision = ActionRuntime().decide(
        "Magyarázd el röviden, mi az a bitcoin."
    )

    assert decision.route == ROUTE_CHAT
    assert decision.use_web is False
    assert decision.market_fallback is False


def test_action_runtime_keeps_memory_architecture_explanation_on_chat_route():
    decision = ActionRuntime().decide(
        "Írj egy részletes, legalább 8–12 bekezdéses magyar összefoglalót arról, "
        "hogyan működik a LocalAI Desktop jelenlegi memóriaarchitektúrája: külön térj ki "
        "a current chat contextre, Window Memoryra, Global Memoryra, cross-window retrievalre, "
        "model switch viselkedésre, persistence-re, a Remember ikonra és a web routing kapcsolatára."
    )

    assert decision.route == ROUTE_CHAT
    assert decision.use_web is False
    assert decision.market_fallback is False


def test_action_runtime_routes_memory_write_before_other_actions():
    decision = ActionRuntime().decide(
        "Jegyezd meg, hogy Lilla a lányom."
    )

    assert decision.route == ROUTE_MEMORY_WRITE
    assert decision.use_web is False


def test_action_runtime_routes_crypto_quote_to_structured_provider_when_available():
    decision = ActionRuntime().decide(
        "Mennyi most a bitcoin árfolyama?",
        crypto_market_available=True,
    )

    assert decision.route == ROUTE_CRYPTO_MARKET
    assert decision.use_web is True
    assert decision.market_fallback is False


def test_action_runtime_routes_stock_quote_to_structured_provider_when_available():
    decision = ActionRuntime().decide(
        "Mennyi most a Tesla részvény ára?",
        multi_asset_market_available=True,
    )

    assert decision.route == ROUTE_MULTI_ASSET_MARKET
    assert decision.use_web is True
    assert decision.market_fallback is False


def test_action_runtime_routes_market_quote_to_compact_web_fallback_without_provider():
    decision = ActionRuntime().decide(
        "Mennyi most a Tesla részvény ára?",
        multi_asset_market_available=False,
    )

    assert decision.route == ROUTE_MARKET_WEB
    assert decision.use_web is True
    assert decision.market_fallback is True


def test_action_runtime_routes_fresh_non_market_request_to_web():
    decision = ActionRuntime().decide(
        "Melyik a jelenlegi legfrissebb Qwen verzió?"
    )

    assert decision.route == ROUTE_WEB
    assert decision.use_web is True


def test_action_runtime_force_web_preserves_web_authority():
    decision = ActionRuntime().decide(
        "Magyarázd el, mi az a bitcoin.",
        force_web=True,
    )

    assert decision.route == ROUTE_WEB
    assert decision.use_web is True


def test_action_runtime_can_route_using_attachment_augmented_model_text():
    decision = ActionRuntime().decide(
        "Mi ennek az aktuális ára?",
        model_text="Mi ennek az aktuális ára?\n\nTSLA stock price",
        force_web=True,
        multi_asset_market_available=True,
    )

    assert decision.route in {ROUTE_MULTI_ASSET_MARKET, ROUTE_WEB}


def test_action_runtime_routes_artifact_request_explicitly():
    decision = ActionRuntime().decide(
        "Készíts egy Red Executive PDF riportot a Bitcoinról."
    )

    assert decision.route == ROUTE_ARTIFACT
    assert decision.use_web is False
    assert decision.plan.artifact_plans[0].request.format == "pdf"


def test_action_runtime_routes_web_grounded_artifact_as_one_contract():
    runtime = ActionRuntime()
    contracts = runtime.plan_many(
        "Mi a legújabb Ollama verzió, és készíts róla egy rövid HTML riportot."
    )

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.route == ROUTE_ARTIFACT
    assert contract.use_web is True
    assert contract.artifact_plans[0].request.format == "html"
    assert contract.required_authorities == (
        AUTH_LOCAL_MODEL,
        AUTH_ARTIFACT_CREATE,
        AUTH_EXTERNAL_READ,
    )


def test_action_runtime_plans_numbered_tasks_independently_in_source_order():
    runtime = ActionRuntime()
    contracts = runtime.plan_many(
        """1. Mennyi most a Bitcoin árfolyama?
2. Magyarázd el röviden, mi az a TCP.
3. Jegyezd meg, hogy a kedvenc tesztszínem a kék.
4. Készíts egy Classic HTML riportot a TCP-ről.""",
        crypto_market_available=True,
    )

    assert [item.index for item in contracts] == [0, 1, 2, 3]
    assert [item.route for item in contracts] == [
        ROUTE_CRYPTO_MARKET,
        ROUTE_CHAT,
        ROUTE_MEMORY_WRITE,
        ROUTE_ARTIFACT,
    ]
    assert contracts[0].prompt.startswith("Mennyi most")
    assert contracts[1].required_authorities == (AUTH_LOCAL_MODEL,)
    assert contracts[2].required_authorities == (AUTH_MEMORY_WRITE,)
    assert contracts[3].artifact_plans[0].request.format == "html"


def test_action_runtime_plans_plain_newline_question_batch_independently():
    runtime = ActionRuntime()
    contracts = runtime.plan_many(
        """Ki Sample Musician?
Mikor írta Wrong Author a Silver Story című művet?
Mikor alakult a Sample Band?""",
        force_web=True,
    )

    assert [contract.prompt for contract in contracts] == [
        "Ki Sample Musician?",
        "Mikor írta Wrong Author a Silver Story című művet?",
        "Mikor alakult a Sample Band?",
    ]
    assert all(contract.route == ROUTE_WEB for contract in contracts)
    assert [
        contract.constraints.request_profile.requested_fact
        for contract in contracts
    ] == ["identity", "temporal", "temporal"]
    assert [
        contract.constraints.request_profile.relation
        for contract in contracts
    ] == ["identity", "authorship_creation", "formation"]
    assert len({
        id(contract.constraints.request_profile)
        for contract in contracts
    }) == 3


def test_action_runtime_keeps_a_wrapped_question_as_one_request():
    contracts = ActionRuntime().plan_many(
        "Mikor alakult\na Sample Band?",
        force_web=True,
    )

    assert len(contracts) == 1
    assert contracts[0].prompt == "Mikor alakult\na Sample Band?"


def test_action_runtime_model_context_suffix_can_help_route_each_unit_without_mutating_prompt():
    runtime = ActionRuntime()
    contracts = runtime.plan_many(
        "1. Mi ennek az aktuális ára?\n2. Magyarázd el röviden.",
        model_context_suffix="\n\nTSLA stock price",
        force_web=True,
        multi_asset_market_available=True,
    )

    assert len(contracts) == 2
    assert contracts[0].prompt == "Mi ennek az aktuális ára?"
    assert contracts[0].route in {ROUTE_MULTI_ASSET_MARKET, ROUTE_WEB}
    assert contracts[1].prompt == "Magyarázd el röviden."


def test_action_runtime_host_authority_validation_fails_closed():
    runtime = ActionRuntime()
    contract = runtime.plan_many(
        "Készíts egy PDF riportot."
    )[0]

    authorization = runtime.authorize(
        contract,
        {AUTH_LOCAL_MODEL},
    )

    assert authorization.allowed is False
    assert authorization.missing_authorities == (AUTH_ARTIFACT_CREATE,)

    try:
        runtime.validate_many(
            [contract],
            {AUTH_LOCAL_MODEL},
        )
    except PermissionError as exc:
        assert "artifact_create" in str(exc)
    else:
        raise AssertionError("missing host authority must fail closed")


def test_action_runtime_default_host_authorities_accept_existing_bounded_actions():
    runtime = ActionRuntime()
    contracts = runtime.plan_many(
        """1. Jegyezd meg, hogy a kedvenc tesztszínem a kék.
2. Mi a jelenlegi legfrissebb Qwen modell?
3. Készíts egy PDF riportot a TCP-ről."""
    )

    assert runtime.validate_many(contracts) == contracts
