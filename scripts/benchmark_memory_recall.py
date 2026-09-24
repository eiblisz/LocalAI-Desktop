"""Bounded, hardware-independent benchmark for current-window recall.

This verifies the application-level fast path only.  It intentionally does
not unload, reload, or otherwise disturb shared Ollama workloads.  Optional
model timing belongs in RequestTrace when a request actually needs a model.
"""

import argparse
import gc
import json
import statistics
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.conversation_memory_recall import is_safe_direct_recall
from app.main_window import MainWindow
from app.memory_store import MemoryStore
from app.request_trace import RequestTrace
from app.task_constraints import build_task_constraints


DEFAULT_STATE = "A tesztprojekt kódneve Kék Sárkány 7319."
DEFAULT_QUERY = "Mi a tesztprojekt kódneve ebben a beszélgetésben?"


def _run_once(store, state, query):
    host = SimpleNamespace(
        generation_chat_id="benchmark-current-window",
        pending_action_history_messages=[{"role": "user", "content": state}],
        memory_store=store,
    )
    trace = RequestTrace("benchmark")
    trace.add_metadata(route="current_window_memory")
    recall = MainWindow._direct_conversation_memory_recall(
        host,
        query,
        trace=trace,
    )
    trace.begin("language_validation")
    direct_allowed = is_safe_direct_recall(
        query,
        recall,
        constraints=build_task_constraints(query),
    )
    trace.end("language_validation", direct_memory_language_valid=direct_allowed)
    if not direct_allowed:
        raise RuntimeError("The benchmark input did not produce a direct recall hit.")

    trace.begin("context_assembly")
    trace.end(
        "context_assembly",
        assembled_context_chars=0,
        estimated_prompt_units=0,
        model_path_skipped=True,
    )
    trace.mark_duration("ollama_queue_or_transport", 0)
    trace.mark_duration("ollama_load", 0)
    trace.mark_duration("ollama_prompt_evaluation", 0)
    trace.mark_duration("ollama_generation", 0)
    trace.begin("post_processing")
    trace.end("post_processing", guard_path="language_validation_only")
    snapshot = trace.snapshot()
    return {
        "route": "current_window_memory",
        "answer": recall.answer,
        "retrieval_ms": round(
            sum(
                snapshot["phases_ms"].get(phase, 0)
                for phase in (
                    "memory_scope_resolution",
                    "current_raw_context_retrieval",
                    "window_memory_retrieval",
                    "direct_memory_recall",
                )
            ),
            2,
        ),
        "context_assembly_ms": snapshot["phases_ms"].get("context_assembly", 0),
        "prompt_tokens": 0,
        "ollama_model_ms": 0,
        "language_validation_ms": snapshot["phases_ms"].get(
            "language_validation",
            0,
        ),
        "post_processing_ms": snapshot["phases_ms"].get("post_processing", 0),
        "total_ms": snapshot["total_ms"],
        "phases_ms": snapshot["phases_ms"],
    }


def _summary(rows):
    def stats(field):
        values = [float(row[field]) for row in rows]
        return {
            "min_ms": round(min(values), 2),
            "median_ms": round(statistics.median(values), 2),
            "max_ms": round(max(values), 2),
        }

    return {
        "runs": len(rows),
        "route": "current_window_memory",
        "fast_path": "direct deterministic current-window user evidence",
        "total": stats("total_ms"),
        "retrieval": stats("retrieval_ms"),
        "context_assembly": stats("context_assembly_ms"),
        "ollama_model": stats("ollama_model_ms"),
        "language_validation": stats("language_validation_ms"),
        "post_processing": stats("post_processing_ms"),
        "prompt_tokens": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=1,
        help="Excluded fast-path warmups before recorded runs (default: 1).",
    )
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.warmup_runs < 0:
        parser.error("--warmup-runs cannot be negative")

    with tempfile.TemporaryDirectory(prefix="localai-memory-benchmark-") as temp_dir:
        store = MemoryStore(Path(temp_dir) / "memory.sqlite3")
        store.upsert_window_memory(
            "benchmark-current-window",
            f"- User: {args.state}",
            compacted_message_count=1,
            source_message_count=1,
        )
        for _ in range(args.warmup_runs):
            _run_once(store, args.state, args.query)
        rows = [_run_once(store, args.state, args.query) for _ in range(args.runs)]
        # MemoryStore opens short-lived sqlite connections.  Force their
        # cleanup before Windows removes the temporary benchmark database.
        del store
        gc.collect()

    print(json.dumps({"summary": _summary(rows), "runs": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
