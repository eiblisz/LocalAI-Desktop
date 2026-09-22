from app import evidence_verifier
from app import web_search_tool
from app import workers


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def test_listing_page_cannot_override_conflicting_product_identity():
    result = {
        "title": "G.Skill 32GB DDR4 (2x16GB) F4-3200C16D-32GVK",
        "url": "https://www.ebay.de/sch/i.html?_nkw=ram",
        "snippet": "DDR4 3200 MHz, 234.95 EUR",
        "page_text": (
            "Other listings include 2x32GB DDR4 3200 MHz kits. "
            "This page contains many different memory products."
        ),
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["exact_kit"]["status"] == evidence_verifier.REJECTED
    assert ledger["verdict"] == "REJECT"


def test_generic_listing_with_conflicting_total_capacity_is_rejected():
    result = {
        "title": "RAM 32GB DDR4 3200 | eBay.de",
        "url": "https://www.ebay.de/sch/i.html?_nkw=ram",
        "snippet": "Memory listings in Germany",
        "page_text": "2x32GB DDR4 3200 MHz kit 189 EUR",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["exact_kit"]["status"] == evidence_verifier.REJECTED
    assert ledger["verdict"] == "REJECT"


def test_matching_total_capacity_can_back_page_level_exact_kit_evidence():
    result = {
        "title": "Corsair Vengeance LPX 64GB Kit DDR4-3200 CL16",
        "url": "https://www.idealo.de/preisvergleich/corsair-64gb.html",
        "snippet": "Gunstigster Preis 599.00 EUR in Deutschland",
        "page_text": (
            "Produktdetails Speicher-Kit 2 x 32 GB. DDR4. "
            "Datentransferrate 3200 MHz."
        ),
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["exact_kit"]["status"] == evidence_verifier.VERIFIED
    assert ledger["fields"]["exact_kit"]["evidence"].startswith("fetched page")
    assert ledger["verdict"] == "ACCEPT"


def test_explicit_lowest_price_marker_can_select_lowest_identity_price():
    result = {
        "title": "Patriot Viper Steel 64GB (2x32GB) DDR4-3200 ab 489.88 EUR",
        "url": "https://www.idealo.de/preisvergleich/patriot-64gb.html",
        "snippet": "489.88 EUR - 770.22 EUR, Germany",
        "page_text": "Patriot Viper Steel 2x32GB DDR4 3200 MHz",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["price"]["status"] == evidence_verifier.VERIFIED
    assert ledger["fields"]["price"]["value"] == 489.88
    assert ledger["verdict"] == "ACCEPT"


def test_ambiguous_multiple_prices_without_lowest_price_marker_stays_unknown():
    result = {
        "title": "Patriot Viper Steel 64GB (2x32GB) DDR4-3200",
        "url": "https://shop.example.de/patriot-64gb",
        "snippet": "Prices shown: 489.88 EUR and 519.48 EUR",
        "page_text": "Patriot Viper Steel 2x32GB DDR4 3200 MHz",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["price"]["status"] == evidence_verifier.UNKNOWN
    assert ledger["verdict"] == "REJECT"


def test_exact_product_with_single_verified_price_is_accepted():
    result = {
        "title": "Kingston Fury Beast 64GB (2x32GB) DDR4 3200MHz Kit",
        "url": "https://shop.example.de/kingston-64gb",
        "snippet": "2x32GB DDR4 3200 MHz kit, 189.90 EUR",
        "page_text": "Kingston Fury Beast memory kit",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["verdict"] == "ACCEPT"
    assert ledger["fields"]["exact_kit"]["status"] == evidence_verifier.VERIFIED
    assert ledger["fields"]["price"]["value"] == 189.90


def test_answer_verifier_rejects_wrong_kit_and_invented_price():
    result = {
        "title": "Kingston Fury Beast 64GB (2x32GB) DDR4 3200MHz Kit",
        "url": "https://shop.example.de/kingston-64gb",
        "snippet": "2x32GB DDR4 3200 MHz kit, 189.90 EUR",
        "page_text": "Kingston Fury Beast memory kit",
    }
    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    wrong_kit = (
        "G.Skill 32GB (2x16GB) DDR4 3200 MHz 189.90 EUR "
        "https://shop.example.de/kingston-64gb"
    )
    valid, reasons = evidence_verifier.verify_answer_against_evidence(
        wrong_kit,
        QUERY,
        [ledger],
    )
    assert not valid
    assert "answer_exact_kit_mismatch" in reasons

    invented_price = (
        "Kingston Fury Beast 2x32GB DDR4 3200 MHz 234.95 EUR "
        "https://shop.example.de/kingston-64gb"
    )
    valid, reasons = evidence_verifier.verify_answer_against_evidence(
        invented_price,
        QUERY,
        [ledger],
    )
    assert not valid
    assert "answer_unverified_price" in reasons


def test_answer_verifier_accepts_only_verified_claims_and_url():
    result = {
        "title": "Kingston Fury Beast 64GB (2x32GB) DDR4 3200MHz Kit",
        "url": "https://shop.example.de/kingston-64gb",
        "snippet": "2x32GB DDR4 3200 MHz kit, 189.90 EUR",
        "page_text": "Kingston Fury Beast memory kit",
    }
    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)
    answer = (
        "Kingston Fury Beast 2x32GB DDR4 3200 MHz - 189.90 EUR: "
        "https://shop.example.de/kingston-64gb"
    )

    valid, reasons = evidence_verifier.verify_answer_against_evidence(
        answer,
        QUERY,
        [ledger],
    )

    assert valid
    assert reasons == []


def test_worker_fails_closed_without_showing_rejected_candidate(monkeypatch):
    plan = web_search_tool.build_search_plan(QUERY)
    bad_result = {
        "title": "G.Skill 32GB DDR4 (2x16GB) 3200MHz",
        "url": "https://www.ebay.de/sch/i.html?_nkw=ram",
        "snippet": "234.95 EUR",
        "page_text": "Other listing: 2x32GB DDR4 3200 MHz 189 EUR",
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
        def __init__(self):
            self.stream_calls = 0

        def chat_once(self, model, messages, timeout=600.0):
            return QUERY

        def chat_stream(self, **kwargs):
            self.stream_calls += 1
            kwargs["on_token"](
                "G.Skill 2x16GB DDR4 3200 MHz 234.95 EUR"
            )

    client = Client()
    tokens = []
    failed = []
    finished = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        QUERY,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    combined = "".join(tokens)
    assert not failed
    assert finished == [True]
    assert client.stream_calls == 0
    assert "2x16GB" not in combined
    assert "234.95" not in combined
    assert "FAIL-CLOSED" not in combined
    assert worker.diagnostic_metadata["evidence_diagnostic"]


def test_worker_buffers_and_replaces_unverified_model_answer(monkeypatch):
    plan = web_search_tool.build_search_plan(QUERY)
    good_result = {
        "title": "Kingston Fury Beast 64GB (2x32GB) DDR4 3200MHz Kit",
        "url": "https://shop.example.de/kingston-64gb",
        "snippet": "2x32GB DDR4 3200 MHz kit, 189.90 EUR",
        "page_text": "Kingston Fury Beast memory kit",
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
            "results": [good_result],
        },
    )

    class Client:
        def chat_once(self, model, messages, timeout=600.0):
            return QUERY

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            on_token(
                "Wrong product 2x16GB DDR4 3200 MHz 234.95 EUR "
                "https://shop.example.de/kingston-64gb"
            )

    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        Client(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        QUERY,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)

    worker.run()

    combined = "".join(tokens)
    assert not failed
    assert "Wrong product" not in combined
    assert "234.95" not in combined
    assert (
        worker.diagnostic_metadata["verification_status"]
        == "Evidence verification: PASS (host-verified fallback used)"
    )
    assert "https://shop.example.de/kingston-64gb" in combined
