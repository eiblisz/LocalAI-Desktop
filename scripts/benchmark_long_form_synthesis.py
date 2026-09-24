"""Print a bounded long-form synthesis acceptance report.

Without ``--live`` this checks policy only and never touches a shared model.
With ``--live`` it runs the canonical stable-general request locally and adds
the completion metadata needed for a Windows maintainer acceptance check.
"""

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import DEFAULT_SYSTEM_PROMPT, PREFERRED_LOCAL_MODEL
from app.long_form_synthesis_benchmark import (
    LONG_FORM_STABLE_GENERAL_PROMPT,
    run_long_form_synthesis_acceptance,
)
from app.ollama_client import OllamaClient
from app.request_trace import RequestTrace
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run one local model generation; omitted by default for safe CI use.",
    )
    parser.add_argument("--model", default=PREFERRED_LOCAL_MODEL)
    args = parser.parse_args(argv)

    report = run_long_form_synthesis_acceptance().to_dict()
    if not args.live:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    trace = RequestTrace("benchmark")
    constraints = build_task_constraints(LONG_FORM_STABLE_GENERAL_PROMPT)
    worker = AdaptiveChatWorker(
        OllamaClient(),
        args.model,
        [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": LONG_FORM_STABLE_GENERAL_PROMPT},
        ],
        LONG_FORM_STABLE_GENERAL_PROMPT,
        allow_web_fallback=False,
        constraints=constraints,
        trace=trace,
        output_budget=report["num_predict"],
        synthesis_route=report["route"],
    )
    errors = []
    worker.failed.connect(errors.append)
    worker.run()
    if errors:
        report.update({
            "done_reason": "incomplete_or_error",
            "generated_count": None,
            "repair_attempts": worker.execution_control.budget.repairs,
            "total_time_note": "informational only; live generation failed safely",
            "error": " ".join(str(errors[0]).split())[:500],
        })
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    pipeline = worker.diagnostic_metadata.get("response_pipeline", {})
    snapshot = trace.snapshot()
    report.update({
        "done_reason": pipeline.get("done_reason") or "unknown",
        "generated_count": pipeline.get("eval_count"),
        "repair_attempts": worker.execution_control.budget.repairs,
        "total_time_note": (
            f"informational only; live total_ms={snapshot['total_ms']}"
        ),
        "total_ms": snapshot["total_ms"],
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
