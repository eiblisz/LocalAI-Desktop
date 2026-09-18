from app.generic_shopping_evidence import (
    build_generic_shopping_queries,
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


def test_inflected_hungarian_shopping_command_is_detected():
    assert is_generic_shopping_request(
        "Keressel nekem 4tb-os ssd merevlemezt"
    )


def test_ssd_shopping_rejects_article_category_comparison_and_hdd_pages():
    results = [
        {
            "title": "SSD kaufen: Warum 4 TB gerade günstiger sind als zweimal 2 TB",
            "url": "https://www.pcgameshardware.de/SSD-Hardware-255552/Specials/SSD-Preise-2026-Preis-pro-Terabyte-Kaufberatung-1553743/",
            "snippet": "4 TB SSD Preise 169,99 EUR",
            "page_text": "",
        },
        {
            "title": "4TB SSDs: Riesiger Speicher mit maximaler Geschwindigkeit",
            "url": "https://www.computeruniverse.net/de/c/hardware-komponenten/ssd-4tb",
            "snippet": "4 TB SSD Kategorie",
            "page_text": "",
        },
        {
            "title": "Hordozható SSD | Külső SSD | Alza.hu",
            "url": "https://www.alza.hu/kulso-ssd-meghajtok/18855664.htm",
            "snippet": "4 TB SSD választék",
            "page_text": "",
        },
        {
            "title": "Külső ssd 4tb ÁrGép",
            "url": "https://www.argep.hu/trend/KUEL/Kuelsoe-ssd-4tb.html",
            "snippet": "4 TB SSD árösszehasonlítás",
            "page_text": "",
        },
        {
            "title": "SSD Merevlemez 4TB | Mediamarkt",
            "url": "https://www.mediamarkt.hu/v/ssd-merevlemez-4tb",
            "snippet": "4 TB SSD kategória",
            "page_text": "",
        },
        {
            "title": "Külső merevlemez - 4TB - iPon.hu",
            "url": "https://ipon.hu/shop/csoport/szamitogep-alkatresz/merevlemez-kulso/192/4-tb/200",
            "snippet": "4 TB külső merevlemez",
            "page_text": "",
        },
    ]

    assert build_generic_shopping_records(QUERY, results) == []


def test_only_explicit_product_url_is_accepted_for_ssd_query():
    results = [
        {
            "title": "Samsung 870 QVO 4TB SSD",
            "url": "https://shop.example.de/product/samsung-870-qvo-4tb",
            "snippet": "Samsung 870 QVO 4 TB SSD 289 EUR",
            "page_text": "",
        },
        {
            "title": "4TB SSD category",
            "url": "https://shop.example.de/ssd/4tb",
            "snippet": "4 TB SSD products",
            "page_text": "",
        },
    ]

    records = build_generic_shopping_records(QUERY, results)

    assert records == [
        {
            "title": "Samsung 870 QVO 4TB SSD",
            "url": "https://shop.example.de/product/samsung-870-qvo-4tb",
            "price": ("EUR", 289.0),
        }
    ]


def test_inflected_ssd_query_builds_product_page_searches():
    queries = build_generic_shopping_queries(
        "Keressel nekem 4tb-os ssd merevlemezt"
    )

    assert len(queries) == 4
    assert all("4 TB SSD" in query for query in queries)
    assert all("merevlemez" not in query.lower() for query in queries)
    assert any("mediamarkt.de/de/product" in query for query in queries)
    assert any("alternate.de" in query for query in queries)
    assert any("amazon.de/dp" in query for query in queries)
    assert any("otto.de/p/" in query for query in queries)

