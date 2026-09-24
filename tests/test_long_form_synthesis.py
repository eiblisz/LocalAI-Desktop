from app.action_runtime import (
    ActionRuntime,
    ROUTE_CHAT,
    ROUTE_MARKET_WEB,
    ROUTE_MULTI_ASSET_MARKET,
    ROUTE_WEB,
)
from app.chat_orchestration import plan_chat_actions
from app.generation_policy import (
    LENGTH_LONG,
    LENGTH_SHORT,
    SYNTHESIS_HYBRID,
    SYNTHESIS_LOCAL,
    SYNTHESIS_WEB,
    build_generation_policy,
    output_budget_for_response_length,
)
from app.grounded_factual_guard import unsupported_grounded_literals
from app.long_form_synthesis_benchmark import (
    LONG_FORM_STABLE_GENERAL_PROMPT,
    run_long_form_synthesis_acceptance,
)
from app.request_semantics import classify_request
from app.user_error_messages import public_error
from app import workers


def _contract(prompt, web_mode="ON"):
    return plan_chat_actions(ActionRuntime(), prompt, web_mode=web_mode)[0]


def test_case_01_stable_general_knowledge_with_web_on_stays_local():
    contract = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    assert contract.route == ROUTE_CHAT
    assert contract.synthesis_policy.synthesis_route == SYNTHESIS_LOCAL
    assert contract.use_web is False


def test_case_02_explicit_long_form_receives_bounded_larger_budget():
    contract = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    assert contract.constraints.response_length == LENGTH_LONG
    assert contract.constraints.output_budget == 2048


def test_case_03_partial_web_coverage_uses_hybrid_synthesis_policy():
    prompt = (
        "Mutasd be részletesen, hogyan működik a neurális háló, "
        "és adj néhány friss példát is."
    )
    contract = _contract(prompt)
    assert contract.route in {ROUTE_WEB, ROUTE_MARKET_WEB, ROUTE_MULTI_ASSET_MARKET}
    assert contract.synthesis_policy.synthesis_route == SYNTHESIS_HYBRID


def test_case_04_fresh_fact_remains_web_required():
    contract = _contract("Mi az NVIDIA jelenlegi részvényára?")
    assert contract.route in {ROUTE_WEB, ROUTE_MARKET_WEB, ROUTE_MULTI_ASSET_MARKET}
    assert contract.synthesis_policy.synthesis_route == SYNTHESIS_WEB
    assert contract.synthesis_policy.web_required is True


def test_case_05_explicit_web_request_remains_web_required():
    contract = _contract("Keress friss forrásokat a mai időjárásról.")
    assert contract.route == ROUTE_WEB
    assert contract.use_web is True


def test_case_06_unsupported_fresh_literal_remains_blocked():
    assert unsupported_grounded_literals(
        "A legújabb verzió 2026-ban jelent meg.",
        "A modell általános működését magyarázó szöveg.",
    ) == ("2026",)


def test_case_07_long_output_budget_is_finite():
    assert output_budget_for_response_length(LENGTH_LONG) == 2048


def test_case_08_length_termination_has_specific_safe_message():
    error = public_error("Ollama stopped at the configured output-token limit.")
    assert error.code == "generation_length_limit"
    assert "csonka" in error.message


def test_case_09_hungarian_long_form_retains_hungarian_policy():
    contract = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    assert contract.constraints.response_language == "hu"
    assert contract.constraints.output_budget >= 2048


def test_case_10_language_guard_constraints_are_preserved():
    contract = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    assert contract.constraints.forbidden_language_drift is True


def test_case_11_current_window_recall_policy_stays_local():
    contract = _contract("Mi a kódnév ebben a beszélgetésben?")
    assert contract.route == ROUTE_CHAT
    assert contract.conversation_local is True


def test_case_12_cross_window_request_does_not_claim_current_window_locality():
    contract = _contract("Mi a másik beszélgetésben megadott kódnév?")
    assert contract.conversation_local is False


def test_case_13_desktop_and_discord_share_contract_policy():
    desktop = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    discord = _contract(LONG_FORM_STABLE_GENERAL_PROMPT)
    assert desktop.synthesis_policy == discord.synthesis_policy
    assert desktop.constraints.output_budget == discord.constraints.output_budget


def test_case_14_short_normal_query_does_not_inflate_budget():
    policy = build_generation_policy(
        "Magyarázd el röviden, mi az a token.",
        profile=classify_request("Magyarázd el röviden, mi az a token."),
    )
    assert policy.response_length == LENGTH_SHORT
    assert policy.output_budget <= 1024


def test_case_15_ambiguous_freshness_keeps_existing_conservative_web_route():
    contract = _contract("Melyik a legfrissebb kiadás?")
    assert contract.route == ROUTE_WEB
    assert contract.synthesis_policy.synthesis_route == SYNTHESIS_WEB


def test_host_policy_acceptance_report_is_bounded_and_machine_readable():
    report = run_long_form_synthesis_acceptance().to_dict()
    assert report == {
        "query_class": "long_form_stable_general",
        "route": "LOCAL",
        "requested_detail": "long",
        "num_predict": 2048,
        "web_required": False,
        "done_reason": "not_run",
        "generated_count": None,
        "repair_attempts": 0,
        "total_time_note": "informational only; no model was started",
    }


def test_hybrid_worker_keeps_stable_explanation_when_web_coverage_is_partial(
    monkeypatch,
):
    prompt = (
        "Mutasd be részletesen, hogyan működik a neurális háló, "
        "és adj néhány friss példát is."
    )

    class HybridClient:
        def chat_once(self, model, messages, timeout=600.0):
            return "neural network current examples"

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            assert "HYBRID SYNTHESIS" in messages[1]["content"]
            if not should_stop():
                on_token(
                    "A neurális háló rétegekben alakítja át a bemenetet, "
                    "ezért összetett mintákat is képes megtanulni."
                )

    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Current example",
                "url": "https://example.test/current",
                "snippet": "One current example.",
            }],
        },
    )
    tokens = []
    failures = []
    worker = workers.ChatWebWorker(
        HybridClient(),
        "local-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
        synthesis_route=SYNTHESIS_HYBRID,
        output_budget=2048,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failures.append)
    worker.run()

    assert failures == []
    assert "neurális háló" in "".join(tokens)
    assert worker.source_metadata == [{
        "title": "Current example",
        "url": "https://example.test/current",
    }]
    assert worker.diagnostic_metadata["evidence_coverage"] == "partial_or_available"
    assert worker.diagnostic_metadata["synthesis_route"] == SYNTHESIS_HYBRID


def test_hybrid_worker_degrades_to_guarded_stable_synthesis_without_sources(
    monkeypatch,
):
    prompt = "Magyarázd el a neurális hálót, és adj friss példákat is."

    class HybridFallbackClient:
        def chat_once(self, model, messages, timeout=600.0):
            return "neural network current examples"

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            assert "could not be verified" in messages[0]["content"]
            if not should_stop():
                on_token(
                    "A neurális háló egymásra épülő rétegekben dolgozza fel a mintákat."
                )

    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [],
        },
    )
    tokens = []
    failures = []
    worker = workers.ChatWebWorker(
        HybridFallbackClient(),
        "local-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
        synthesis_route=SYNTHESIS_HYBRID,
        output_budget=2048,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failures.append)
    worker.run()

    assert failures == []
    assert "neurális háló" in "".join(tokens)
    assert worker.diagnostic_metadata["evidence_coverage"] == (
        "unavailable_for_web_augmentation"
    )
