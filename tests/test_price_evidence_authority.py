from app import evidence_verifier


QUERY = (
    "Keress nekem 2x32GB DDR4 3200 MHz RAM kitet "
    "Nemetorszagban 700 EUR alatt, es adj kozvetlen linkeket is."
)


def test_title_product_price_beats_lower_shipping_price_in_snippet():
    result = {
        "title": "Crucial SO-DIMM 64GB Kit ab 606,90 EUR | Preisvergleich Geizhals Deutschland",
        "url": "https://geizhals.de/crucial-64gb-kit.html",
        "snippet": "2x32GB DDR4 3200 MHz. Versand ab 3,11 EUR.",
        "page_text": "Crucial 64GB Speicher-Kit 2 x 32 GB DDR4 3200 MHz.",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["price"]["status"] == evidence_verifier.VERIFIED
    assert ledger["fields"]["price"]["value"] == 606.90
    assert ledger["fields"]["price"]["evidence"].startswith("result title")
    assert ledger["verdict"] == "ACCEPT"


def test_snippet_price_is_used_when_title_has_no_price():
    result = {
        "title": "Kingston Fury Beast 64GB 2x32GB DDR4 3200MHz Kit",
        "url": "https://shop.example.de/kingston-64gb",
        "snippet": "189,90 EUR in Deutschland",
        "page_text": "Kingston Fury Beast memory kit",
    }

    ledger = evidence_verifier.build_evidence_ledger(QUERY, result)

    assert ledger["fields"]["price"]["status"] == evidence_verifier.VERIFIED
    assert ledger["fields"]["price"]["value"] == 189.90
    assert ledger["fields"]["price"]["evidence"] == "result snippet"
    assert ledger["verdict"] == "ACCEPT"
