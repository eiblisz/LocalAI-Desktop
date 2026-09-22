import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.web_search_tool import search_web


DEFAULT_QUERIES = (
    "latest Ollama version",
    "current Qwen model family",
)


def run_mode(mode, queries):
    old = os.environ.get("BRAVE_CONTEXT_MODE")
    os.environ["BRAVE_CONTEXT_MODE"] = mode
    rows = []
    try:
        for query in queries:
            try:
                payload = search_web(query, max_results=6, fetch_pages=True)
                timing = dict(payload.get("timing") or {})
                rows.append({
                    "query": query,
                    "mode": mode,
                    "provider": payload.get("provider", ""),
                    "page_fetch_count": timing.get("page_fetch_count", 0),
                    "provider_ms": timing.get("provider_ms", 0),
                    "page_fetch_ms": timing.get("page_fetch_ms", 0),
                    "total_search_ms": timing.get("total_search_ms", 0),
                    "context_chars": timing.get("context_chars", 0),
                    "usable_sources": timing.get("usable_sources", 0),
                    "fallback_errors": list(payload.get("provider_chain_errors") or []),
                })
            except Exception as exc:
                rows.append({
                    "query": query,
                    "mode": mode,
                    "error": " ".join(str(exc).split())[:500],
                })
    finally:
        if old is None:
            os.environ.pop("BRAVE_CONTEXT_MODE", None)
        else:
            os.environ["BRAVE_CONTEXT_MODE"] = old
    return rows


def main():
    queries = tuple(arg for arg in sys.argv[1:] if arg.strip()) or DEFAULT_QUERIES
    report = {
        "legacy": run_mode("legacy", queries),
        "llm_context": run_mode("llm_context", queries),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
