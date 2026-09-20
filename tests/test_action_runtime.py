from app.action_runtime import (
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
