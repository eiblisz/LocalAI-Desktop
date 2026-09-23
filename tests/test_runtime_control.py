import time

import pytest

from app.runtime_control import (
    CancellationToken,
    ExecutionBudget,
    ExecutionBudgetExceeded,
    ExecutionCancelled,
    ExecutionControl,
)


def test_cancellation_token_runs_registered_close_callback_once():
    token = CancellationToken()
    calls = []

    token.register(lambda: calls.append("closed"))
    token.cancel()
    token.cancel()

    assert calls == ["closed"]
    assert token.is_cancelled() is True
    with pytest.raises(ExecutionCancelled):
        token.throw_if_cancelled()


def test_execution_budget_limits_model_calls():
    control = ExecutionControl(
        budget=ExecutionBudget(timeout_seconds=60, max_model_calls=2)
    )

    assert control.claim_model_call() == 1
    assert control.claim_model_call() == 2
    with pytest.raises(ExecutionBudgetExceeded):
        control.claim_model_call()


def test_execution_budget_deadline_fails_closed():
    budget = ExecutionBudget(timeout_seconds=1, max_model_calls=2)
    budget.started_at = time.monotonic() - 5

    with pytest.raises(ExecutionBudgetExceeded):
        budget.check()


def test_request_timeout_is_bounded_by_remaining_deadline():
    budget = ExecutionBudget(timeout_seconds=30, max_model_calls=2)

    timeout = budget.request_timeout(default=600)

    assert 1 <= timeout <= 30


def test_direct_fact_profile_gets_a_narrow_request_scoped_budget():
    from app.request_semantics import classify_request

    control = ExecutionControl.for_request_profile(
        classify_request("Mikor írta Sample Author a Sample Work című művet?")
    )

    assert control.budget.timeout_seconds == 45
    assert control.budget.max_model_calls == 2
    assert control.claim_search() == 1
    assert control.claim_page_fetch() == 1
    assert control.claim_repair() == 1
    assert control.claim_search() == 2
    with pytest.raises(ExecutionBudgetExceeded):
        control.claim_search()
