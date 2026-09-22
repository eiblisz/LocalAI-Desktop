from dataclasses import asdict, dataclass
from typing import Callable

from .action_runtime import ActionRuntime, ROUTE_CHAT, ROUTE_WEB
from .context_guard import stale_subject_substitution
from .direct_fact import requested_fact_supported
from .language_policy import response_language_matches
from .request_semantics import TASK_COMPARISON, TASK_DIRECT_FACT, classify_request
from .response_guard import unexpected_script_issues, validate_response
from .runtime_control import ExecutionBudget, ExecutionBudgetExceeded, ExecutionControl
from .task_constraints import build_task_constraints


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class BenchmarkReport:
    passed: int
    failed: int
    total: int
    results: tuple[BenchmarkResult, ...]

    def to_dict(self):
        return {
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "results": [asdict(item) for item in self.results],
        }


def _case(name: str, fn: Callable[[], None]) -> BenchmarkResult:
    try:
        fn()
    except Exception as exc:
        return BenchmarkResult(name=name, passed=False, detail=str(exc))
    return BenchmarkResult(name=name, passed=True)


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _benchmark_parent_binding():
    prompt = (
        "Válaszolj kizárólag magyarul az AI Desktop munkanapjáról.\n"
        "1. Hogyan indul a reggel?\n"
        "2. Hogyan kezeli a dokumentumokat?\n"
        "3. Hogyan zárul a nap?"
    )
    contracts = ActionRuntime().plan_many(prompt)
    _assert(len(contracts) == 3, "planner did not preserve three subtasks")
    parent = contracts[0].constraints.parent_intent
    _assert(all(item.constraints.parent_intent == parent for item in contracts),
            "split subtasks lost the canonical parent task")
    _assert(all(item.constraints.response_language == "hu" for item in contracts),
            "split subtasks lost Hungarian response language")


def _benchmark_web_modes():
    runtime = ActionRuntime()
    auto = runtime.plan_many("Melyik a jelenlegi legfrissebb Ollama verzió?")
    off = runtime.plan_many(
        "Keress rá a weben a legfrissebb Qwen modellre.",
        disable_web=True,
    )
    on = runtime.plan_many("Írj egy rövid verset az őszről.", force_web=True)

    _assert(auto[0].route == ROUTE_WEB and auto[0].use_web,
            "WEB AUTO did not route a freshness-sensitive request to web")
    _assert(off[0].route == ROUTE_CHAT and not off[0].use_web,
            "WEB OFF did not force LOCAL ONLY")
    _assert(on[0].route == ROUTE_WEB and on[0].use_web,
            "WEB ON did not force web routing")


def _benchmark_script_guard():
    prompt = "Válaszolj magyarul röviden."
    constraints = build_task_constraints(prompt)
    hangul = unexpected_script_issues(
        prompt,
        "Ez magyar mondat, de 잘못 szó került bele.",
        constraints=constraints,
    )
    cjk = unexpected_script_issues(
        prompt,
        "Ez magyar szöveg 日本 véletlen beszúrással.",
        constraints=constraints,
    )
    clean = validate_response(
        prompt,
        "Ez teljesen magyar válasz.",
        constraints=constraints,
    )

    _assert("unexpected_hangul" in hangul,
            "Hangul leakage was not detected")
    _assert("unexpected_cjk" in cjk,
            "CJK leakage was not detected")
    _assert(clean.valid, "clean Hungarian response was rejected")


def _benchmark_context_drift():
    current = "Melyik a Tesla aktuális ára?"
    constraints = build_task_constraints(current)
    messages = [
        {"role": "user", "content": "Melyik a Bitcoin aktuális ára?"},
        {"role": "assistant", "content": "A Bitcoin ára..."},
        {"role": "user", "content": current},
    ]
    stale = stale_subject_substitution(
        current,
        "A Bitcoin aktuális ára 60 000 USD.",
        messages,
        constraints=constraints,
    )
    followup = stale_subject_substitution(
        "És ennek mennyi az ára?",
        "A Tesla ára...",
        messages,
        constraints=build_task_constraints("És ennek mennyi az ára?"),
    )

    _assert("Bitcoin" in stale,
            "stale Bitcoin->Tesla subject substitution was not detected")
    _assert(followup == (),
            "legitimate referential follow-up was incorrectly blocked")


def _benchmark_runtime_budget():
    budget = ExecutionBudget(timeout_seconds=60, max_model_calls=2)
    budget.claim_model_call()
    budget.claim_model_call()
    try:
        budget.claim_model_call()
    except ExecutionBudgetExceeded:
        return
    raise AssertionError("model-call budget did not fail closed")


def _benchmark_request_semantics_v2():
    direct = classify_request("Mikor írta Wrong Author a Silver Story című művet?")
    comparison = classify_request("Hasonlítsd össze részletesen Alpha és Beta rendszert.")

    _assert(direct.kind == TASK_DIRECT_FACT, "temporal lookup lost direct-fact activity")
    _assert(direct.requested_fact == "temporal", "temporal request was not represented")
    _assert(
        comparison.kind == TASK_COMPARISON and comparison.response_depth == "detailed",
        "detailed modifier overwrote comparison activity",
    )


def _benchmark_direct_fact_sufficiency():
    authorship_only = {
        "results": [{"snippet": "Silver Story was written by Correct Author."}],
    }
    temporal = {
        "results": [{"snippet": "Silver Story was published in 1912."}],
    }
    _assert(
        not requested_fact_supported(authorship_only, "temporal"),
        "authorship alone incorrectly satisfied a temporal request",
    )
    _assert(
        requested_fact_supported(temporal, "temporal"),
        "date evidence did not satisfy a temporal request",
    )


def _benchmark_hungarian_default_and_direct_budget():
    _assert(
        not response_language_matches(
            "Ambiguous entity", "The response remains entirely in English with many words."
        ),
        "ambiguous turn did not retain Hungarian default",
    )
    control = ExecutionControl.for_request_profile(
        classify_request("Mikor írta Sample Author a Sample Work című művet?")
    )
    _assert(control.budget.max_search_calls == 1, "direct lookup search was not bounded")
    _assert(control.budget.max_page_fetches == 1, "direct lookup page fetch was not bounded")


def run_host_orchestration_benchmark() -> BenchmarkReport:
    cases = (
        ("parent_task_binding", _benchmark_parent_binding),
        ("web_mode_routing", _benchmark_web_modes),
        ("language_script_guard", _benchmark_script_guard),
        ("context_entity_drift", _benchmark_context_drift),
        ("runtime_budget", _benchmark_runtime_budget),
        ("request_semantics_v2", _benchmark_request_semantics_v2),
        ("direct_fact_sufficiency", _benchmark_direct_fact_sufficiency),
        ("hungarian_default_direct_budget", _benchmark_hungarian_default_and_direct_budget),
    )
    results = tuple(_case(name, fn) for name, fn in cases)
    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed
    return BenchmarkReport(
        passed=passed,
        failed=failed,
        total=len(results),
        results=results,
    )
