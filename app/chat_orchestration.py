from .text_normalization import canonical_match_text


WEB_MODES = {"AUTO", "ON", "OFF"}


def normalize_web_mode(value):
    mode = str(value or "AUTO").strip().upper()
    return mode if mode in WEB_MODES else "AUTO"


def _semantic_tokens(value):
    return {
        token
        for token in canonical_match_text(value).split()
        if len(token) >= 3
    }


def is_conversation_local_request(
    user_text,
    *,
    conversation_messages=(),
    window_memory="",
):
    """Classify requests whose authority is the current conversation, not the web."""
    normalized_words = set(canonical_match_text(user_text).split())
    tokens = _semantic_tokens(user_text)
    if not tokens:
        return False

    scope_terms = {
        "beszelgetes", "beszelgetesben", "beszelgetesnek",
        "chat", "chatben", "szal", "szalban", "kontextus", "kontextusban",
        "conversation", "chat", "thread", "context",
        "gesprach", "chat", "verlauf", "kontext",
    }
    deictic_terms = {
        "ebben", "ennek", "ezen", "itt", "aktualis",
        "this", "current", "our", "here",
        "dies", "diesem", "dieser", "unser", "hier",
    }
    recall_stems = (
        "emleksz", "felidez", "remember", "recall", "erinner",
    )
    communication_stems = (
        "mondtam", "kozoltem", "megadtam", "said", "told", "provided", "gave",
        "gesagt", "genannt",
    )
    prior_stems = (
        "korabb", "elobb", "earlier", "previously", "before", "vorher",
    )
    has_scope = bool(tokens & scope_terms) and bool(tokens & deictic_terms)
    has_recall = any(
        token.startswith(stem)
        for token in tokens
        for stem in recall_stems
    )
    has_communication = any(
        token.startswith(stem)
        for token in tokens
        for stem in communication_stems
    )
    has_prior = any(
        token.startswith(stem)
        for token in tokens
        for stem in prior_stems
    )
    first_person = bool(
        normalized_words.intersection({"en", "i", "me", "my", "nekem", "tolem", "ich"})
    )
    return bool(
        has_scope
        or has_recall
        or (has_communication and (has_prior or first_person))
    )


def plan_chat_actions(
    action_runtime,
    user_text,
    *,
    web_mode="AUTO",
    model_context_suffix="",
    crypto_market_available=False,
    multi_asset_market_available=False,
    conversation_messages=(),
    window_memory="",
    trace=None,
):
    """Canonical frontend-neutral action planning entry point."""
    mode = normalize_web_mode(web_mode)
    if trace is not None:
        trace.begin("routing")
    def conversation_local_resolver(unit):
        return is_conversation_local_request(
            unit,
            conversation_messages=conversation_messages,
            window_memory=window_memory,
        )

    contracts = action_runtime.plan_many(
        user_text,
        model_context_suffix=model_context_suffix,
        force_web=False,
        disable_web=mode == "OFF",
        conversation_local=conversation_local_resolver,
        crypto_market_available=crypto_market_available,
        multi_asset_market_available=multi_asset_market_available,
    )
    validated = action_runtime.validate_many(contracts)
    conversation_local_count = sum(
        1 for contract in validated if contract.conversation_local
    )
    if trace is not None:
        trace.end(
            "routing",
            web_mode=mode,
            routes=",".join(str(item.route) for item in validated),
            batch_size=len(validated),
            conversation_local_count=conversation_local_count,
        )
    return validated
