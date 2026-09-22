WEB_MODES = {"AUTO", "ON", "OFF"}


def normalize_web_mode(value):
    mode = str(value or "AUTO").strip().upper()
    return mode if mode in WEB_MODES else "AUTO"


def plan_chat_actions(
    action_runtime,
    user_text,
    *,
    web_mode="AUTO",
    model_context_suffix="",
    crypto_market_available=False,
    multi_asset_market_available=False,
):
    """Canonical frontend-neutral action planning entry point."""
    mode = normalize_web_mode(web_mode)
    contracts = action_runtime.plan_many(
        user_text,
        model_context_suffix=model_context_suffix,
        force_web=mode == "ON",
        disable_web=mode == "OFF",
        crypto_market_available=crypto_market_available,
        multi_asset_market_available=multi_asset_market_available,
    )
    return action_runtime.validate_many(contracts)
