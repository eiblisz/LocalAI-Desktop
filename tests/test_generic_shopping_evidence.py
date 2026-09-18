from app.generic_shopping_evidence import (
    build_generic_shopping_records,
    is_generic_shopping_request,
    render_generic_shopping_answer,
)


QUERY = "Keress nekem 4 TB-os SSD-t"


def test_detects_unconstrained_hungarian_shopping_request():
    assert is_generic_shopping_request(QUERY)
    assert not is_generic_shopping_request("Keress ra a legfrissebb Qwen hirekre")


def test_ssd_generic_category_pages_are_rejected_but_product_page_is_kept():
    results = [
        {
            "title": "4 TB SSD (2026) Preisvergleich",
            "url": "https://www.idealo.de/preisvergleich/ProductCategory/14613F9786619.html",
            "snippet": "4 TB SSD Preisvergleich",
            "page_text": "",
        },
        {
            "title": "4 TB NVMe SSDs | M.2 PCIE SSDs | Crucial.com",
            "url": "https://www.crucial.de/catalog/ssd/nvme/4-tb",
            "snippet": "4 TB SSD catalog",
            "page_text": "",
        },
        {
            "title": "Ich kaufte eine 4TB SSD fuer 40 EUR",
            "url": "https://www.youtube.com/watch?v=example",
            "snippet": "4 TB SSD video",
            "page_text": "",
        },
        {
            "title": "SAMSUNG 870 QVO 4TB, 4 TB, SSD, 2,5 Zoll, intern",
            "url": "https://www.mediamarkt.de/de/product/_samsung-870-qvo-4tb-12345.html",
            "snippet": "SAMSUNG 870 QVO 4TB SSD 289,00 EUR",
            "page_text": "",
        },
    ]

    records = build_generic_shopping_records(QUERY, results)

    assert records == [
        {
            "title": "SAMSUNG 870 QVO 4TB, 4 TB, SSD, 2,5 Zoll, intern",
            "url": "https://www.mediamarkt.de/de/product/_samsung-870-qvo-4tb-12345.html",
            "price": ("EUR", 289.0),
        }
    ]


def test_requested_capacity_must_be_present_in_product_evidence():
    records = build_generic_shopping_records(
        QUERY,
        [{
            "title": "Samsung 990 PRO 2TB SSD",
            "url": "https://shop.example.de/product/samsung-990-pro-2tb",
            "snippet": "Fast 2 TB SSD",
            "page_text": "",
        }],
    )

    assert records == []


def test_ambiguous_page_prices_are_not_exposed():
    records = build_generic_shopping_records(
        QUERY,
        [{
            "title": "Example 4TB SSD",
            "url": "https://shop.example.de/product/example-4tb",
            "snippet": "Example 4TB SSD",
            "page_text": "Variant A 299 EUR Variant B 349 EUR",
        }],
    )

    assert records[0]["price"] is None


def test_hungarian_renderer_never_invents_missing_specs():
    answer = render_generic_shopping_answer(
        QUERY,
        [{
            "title": "Example 4TB SSD",
            "url": "https://shop.example.de/product/example-4tb",
            "price": None,
        }],
    )

    assert answer.startswith("Ellenőrzött termékszintű találatok:")
    assert "Example 4TB SSD" in answer
    assert "https://shop.example.de/product/example-4tb" in answer
    assert "MB/s" not in answer
    assert "PCIe" not in answer
    assert "nem egészítettem ki" in answer


def test_hungarian_renderer_fails_closed_without_product_evidence():
    answer = render_generic_shopping_answer(QUERY, [])

    assert "Nem találtam olyan termékszintű forrást" in answer
    assert "Nem fogok kitalált árat vagy specifikációt" in answer


def test_generic_web_search_is_not_misclassified_as_shopping():
    assert not is_generic_shopping_request("Keress nekem valamit az interneten")

