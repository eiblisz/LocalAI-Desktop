from app import web_search_tool
from app import workers


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def test_evidence_diagnostic_reports_only_unverified_required_fields():
    ledger = {
        "title": "Example 64GB RAM kit",
        "required": ["url", "exact_kit", "memory_type", "price"],
        "fields": {
            "url": {
                "status": "VERIFIED",
                "evidence": "result URL",
            },
            "exact_kit": {
                "status": "UNKNOWN",
                "evidence": "no product-level exact-kit identity evidence",
            },
            "memory_type": {
                "status": "VERIFIED",
                "evidence": "result title/snippet identity",
            },
            "price": {
                "status": "REJECTED",
                "evidence": "fetched page: above maximum",
            },
        },
    }

    diagnostic = workers.ChatWebWorker._evidence_diagnostic([ledger])

    assert "Candidate 1" in diagnostic
    assert "Example 64GB RAM kit" not in diagnostic
    assert "exact_kit=UNKNOWN" in diagnostic
    assert "price=REJECTED" in diagnostic
    assert "url=VERIFIED" not in diagnostic
    assert "memory_type=VERIFIED" not in diagnostic


def test_evidence_diagnostic_is_bounded_to_six_candidates():
    ledgers = []
    for index in range(8):
        ledgers.append({
            "title": f"Hidden product {index + 1}",
            "required": ["price"],
            "fields": {
                "price": {
                    "status": "UNKNOWN",
                    "evidence": "no product-specific price evidence",
                }
            },
        })

    diagnostic = workers.ChatWebWorker._evidence_diagnostic(ledgers)

    assert "Candidate 1" in diagnostic
    assert "Candidate 6" in diagnostic
    assert "Candidate 7" not in diagnostic
    assert "Hidden product" not in diagnostic


def test_worker_fail_closed_output_includes_candidate_rejection_reason(monkeypatch):
    plan = web_search_tool.build_search_plan(QUERY)
    bad_result = {
        "title": "RAM 32GB DDR4 3200 | eBay.de",
        "url": "https://www.ebay.de/sch/i.html?_nkw=ram",
        "snippet": "Memory listings in Germany, 189 EUR",
        "page_text": "Other listing: 2x32GB DDR4 3200 MHz kit",
    }

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: [QUERY],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "search_plan": plan,
            "results": [bad_result],
        },
    )

    class Client:
        def chat_stream(self, **kwargs):
            raise AssertionError("model answer must not run without accepted evidence")

    tokens = []
    failed = []
    finished = []
    worker = workers.ChatWebWorker(
        Client(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        QUERY,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    combined = "".join(tokens)
    assert failed == []
    assert finished == [True]
    assert "FAIL-CLOSED (0 accepted products)" in combined
    assert "Evidence diagnostic:" in combined
    assert "Candidate 1" in combined
    assert "exact_kit=REJECTED" in combined
    assert "total-capacity conflict" in combined
    assert "RAM 32GB DDR4 3200 | eBay.de" not in combined
    assert "2x16GB" not in combined
