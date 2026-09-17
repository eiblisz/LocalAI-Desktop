from app import evidence_verifier


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def _accepted_ledger():
    result = {
        "title": "Crucial 64GB Kit DDR4-3200 ab 606,90 EUR",
        "url": "https://shop.example.de/crucial-64gb",
        "snippet": "2x32GB DDR4 3200 MHz Germany",
        "page_text": "Crucial memory kit",
    }
    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)
    assert ledger["verdict"] == "ACCEPT"
    assert ledger["fields"]["price"]["value"] == 606.90
    return ledger


def test_answer_verifier_accepts_standard_whole_euro_rounding_of_verified_price():
    ledger = _accepted_ledger()
    answer = (
        "Crucial 2x32GB DDR4 3200 MHz - kb. 607 EUR: "
        "https://shop.example.de/crucial-64gb"
    )

    valid, reasons = evidence_verifier.verify_answer_against_evidence(
        answer,
        QUERY,
        [ledger],
    )

    assert valid
    assert reasons == []


def test_answer_verifier_still_rejects_unrelated_nearby_price():
    ledger = _accepted_ledger()
    answer = (
        "Crucial 2x32GB DDR4 3200 MHz - 608 EUR: "
        "https://shop.example.de/crucial-64gb"
    )

    valid, reasons = evidence_verifier.verify_answer_against_evidence(
        answer,
        QUERY,
        [ledger],
    )

    assert not valid
    assert "answer_unverified_price" in reasons
