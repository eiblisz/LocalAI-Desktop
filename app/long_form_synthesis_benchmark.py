"""Bounded, hardware-independent acceptance report for long-form synthesis."""

from dataclasses import asdict, dataclass

from .action_runtime import ActionRuntime
from .chat_orchestration import plan_chat_actions


LONG_FORM_STABLE_GENERAL_PROMPT = (
    "Írj egy részletes, legalább 10 bekezdéses magyar összefoglalót arról, "
    "hogyan működik a mesterséges intelligencia általánosságban. Térj ki a "
    "gépi tanulásra, neurális hálókra, nagy nyelvi modellekre, tokenekre, "
    "context windowra, trainingre, inference-re, hallucinationre, tool use-ra "
    "és a lokális modellek előnyeire-hátrányaira."
)


@dataclass(frozen=True)
class LongFormSynthesisAcceptance:
    query_class: str
    route: str
    requested_detail: str
    num_predict: int
    web_required: bool
    done_reason: str
    generated_count: int | None
    repair_attempts: int
    total_time_note: str

    def to_dict(self):
        return asdict(self)


def run_long_form_synthesis_acceptance():
    """Report host-side policy only; deliberately does not start a model."""
    contracts = plan_chat_actions(
        ActionRuntime(),
        LONG_FORM_STABLE_GENERAL_PROMPT,
        web_mode="ON",
    )
    if len(contracts) != 1:
        raise RuntimeError("Long-form acceptance prompt was split unexpectedly.")
    contract = contracts[0]
    policy = contract.synthesis_policy
    return LongFormSynthesisAcceptance(
        query_class="long_form_stable_general",
        route=policy.synthesis_route,
        requested_detail=policy.response_length,
        num_predict=policy.output_budget,
        web_required=policy.web_required,
        # Completion belongs to a real, optional model run. This host-only
        # acceptance intentionally remains safe for CI and shared Windows GPUs.
        done_reason="not_run",
        generated_count=None,
        repair_attempts=0,
        total_time_note="informational only; no model was started",
    )
