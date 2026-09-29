from .internal_authority import is_internal_project_authority_request
from .memory_scope import (
    is_global_memory_request,
    is_memory_architecture_topic_request,
    is_other_window_request,
    resolve_memory_context_scope,
)
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
    normalized_sequence = canonical_match_text(user_text).split()
    normalized_words = set(normalized_sequence)
    tokens = _semantic_tokens(user_text)
    if not tokens:
        return False
    if is_memory_architecture_topic_request(user_text):
        return False

    memory_terms = {
        "memoria", "memory", "gedachtnis",
    }
    durable_scope_terms = {
        "globalis", "globalisan", "tartos",
        "global", "globally", "durable",
        "langzeit", "dauerhaft",
    }
    recall_stems = (
        "emleksz", "felidez", "remember", "recall", "erinner",
    )
    has_recall = any(
        token.startswith(stem)
        for token in tokens
        for stem in recall_stems
    )
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
    if is_other_window_request(user_text):
        return False

    has_scope = bool(tokens & scope_terms) and bool(tokens & deictic_terms)
    adjacent_pairs = set(zip(normalized_sequence, normalized_sequence[1:]))
    has_durable_scope = bool(tokens & durable_scope_terms) or bool(
        adjacent_pairs.intersection({
            ("long", "term"),
            ("hosszu", "tavu"),
        })
    )
    if has_durable_scope and (tokens & memory_terms or has_recall):
        return False
    if has_scope:
        return True

    communication_stems = (
        "mondtam", "kozoltem", "megadtam", "said", "told", "provided", "gave",
        "gesagt", "genannt",
    )
    prior_stems = (
        "korabb", "elobb", "earlier", "previously", "before", "vorher",
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
        has_recall
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

    def local_authority_resolver(unit):
        return bool(
            conversation_local_resolver(unit)
            or is_other_window_request(unit)
            or is_global_memory_request(unit)
            or is_memory_architecture_topic_request(unit)
            or is_internal_project_authority_request(unit)
        )

    contracts = action_runtime.plan_many(
        user_text,
        model_context_suffix=model_context_suffix,
        # WEB ON means public/external requests may use web authority. Local
        # conversation, memory and host/project authority always wins.
        force_web=mode == "ON",
        disable_web=lambda unit: bool(
            mode == "OFF" or local_authority_resolver(unit)
        ),
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
            routing_reasons=",".join(
                str(getattr(item, "routing_reason", ""))
                for item in validated
            ),
            batch_size=len(validated),
            conversation_local_count=conversation_local_count,
            internal_project_authority_count=sum(
                1
                for item in validated
                if bool(getattr(item, "internal_project_authority", False))
            ),
            memory_write_intent_count=sum(
                1
                for item in validated
                if bool(getattr(item, "memory_write_intent", False))
            ),
        )
    return validated
