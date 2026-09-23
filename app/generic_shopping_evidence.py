import re
from urllib.parse import parse_qs, urlparse

from .language_policy import detect_user_language
from .text_normalization import canonical_match_text
from .web_research_pipeline import is_generic_shopping_url


_INFO_QUERY_MARKERS = {
    "hirek",
    "hir",
    "news",
    "latest",
    "legfrissebb",
    "release",
    "cikk",
    "article",
    "weather",
    "idojaras",
    "dokumentacio",
    "documentation",
}

_STRONG_SHOPPING_MARKERS = (
    "keress nekem",
    "hol lehet venni",
    "hol kaphato",
    "mennyi az ara",
    "mennyi az ar",
    "vasarolni",
    "megvenni",
    "find me",
    "where can i buy",
    "buy ",
    "price ",
    "prices ",
    "suche mir",
    "wo kaufen",
    "preis ",
)

_NON_PRODUCT_HOST_MARKERS = (
    "youtube.",
    "reddit.",
    "wikipedia.",
)

_GENERIC_PATH_MARKERS = (
    "/preisvergleich/productcategory",
    "/productcategory/",
    "/catalog/",
    "/categories/",
    "/category/",
    "/collections/",
    "/ul/",
    "/specials/",
    "/news/",
    "/ratgeber/",
    "/guide/",
    "/blog/",
    "/de/c/",
    "/shop/csoport/",
    "/trend/",
    "/v/",
)

_GENERIC_TITLE_MARKERS = (
    "preisvergleich",
    "price comparison",
    "online kaufen",
    "guenstig online kaufen",
    "gunstig online kaufen",
    "aktuelle angebote",
    "angebote",
    "catalog",
    "katalog",
    "category",
    "kategorie",
    "kleinanzeigen",
)


def _fold(value):
    return canonical_match_text(value)


_PRODUCT_QUERY_MARKERS = {
    "ssd", "hdd", "ram", "memoria", "memory", "gpu", "videokartya",
    "monitor", "laptop", "notebook", "telefon", "phone", "tablet",
    "teaskanna", "kettle", "kanna", "keyboard", "billentyuzet", "mouse",
    "eger", "headset", "fejhallgato", "speaker", "hangszoro", "router",
    "nas", "drive", "merevlemez", "festplatte", "akku", "battery",
}


def _has_product_signal(folded, tokens):
    if tokens.intersection(_PRODUCT_QUERY_MARKERS):
        return True
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:gb|tb)\b", folded):
        return True
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:eur|usd)\b", folded):
        return True
    if re.search(r"(?:€|\$)\s*\d", folded):
        return True
    return False


def is_generic_shopping_request(text):
    folded = _fold(text)
    if not folded:
        return False

    tokens = set(re.findall(r"[a-z0-9]+", folded))
    if tokens.intersection(_INFO_QUERY_MARKERS):
        return False
    if not _has_product_signal(folded, tokens):
        return False

    if any(marker in folded for marker in _STRONG_SHOPPING_MARKERS):
        return True

    if re.search(r"\bkeress[a-z0-9]*\b", folded):
        return True

    return False


def _shopping_subject(text):
    raw = " ".join(str(text or "").split())
    raw = re.sub(
        r"^\s*keress\w*\s+(?:nekem\s+)?",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    raw = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*tb(?:-?os)?\b",
        lambda match: f"{match.group(1).replace(',', '.')} TB",
        raw,
        flags=re.IGNORECASE,
    )
    raw = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*gb(?:-?os)?\b",
        lambda match: f"{match.group(1).replace(',', '.')} GB",
        raw,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bssd\b", raw, flags=re.IGNORECASE):
        raw = re.sub(
            r"\bmerevlemez(?:t|et)?\b",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(r"\bssd\b", "SSD", raw, flags=re.IGNORECASE)
    if re.search(r"\bhdd\b", raw, flags=re.IGNORECASE):
        raw = re.sub(r"\bhdd\b", "HDD", raw, flags=re.IGNORECASE)
    raw = " ".join(raw.split())
    return raw[:160] or "product"


def build_generic_shopping_queries(user_prompt):
    subject = _shopping_subject(user_prompt)
    folded = _fold(subject)
    electronics = any(
        token in set(re.findall(r"[a-z0-9]+", folded))
        for token in {"ssd", "hdd", "ram", "gpu", "videokartya", "monitor", "laptop", "router", "nas"}
    )

    if electronics:
        targets = (
            "site:mediamarkt.de/de/product",
            "site:alternate.de product",
            "site:amazon.de/dp",
            "site:otto.de/p/",
        )
    else:
        targets = (
            "site:amazon.de/dp",
            "site:otto.de/p/",
            "site:ebay.de/itm",
            "site:kaufland.de/product",
        )

    return [f"{subject} {target}" for target in targets]


def _capacity_tokens(text):
    values = set()
    for match in re.finditer(
        r"\b(\d+(?:[.,]\d+)?)\s*(gb|tb)\b",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        amount = match.group(1).replace(",", ".")
        if amount.endswith(".0"):
            amount = amount[:-2]
        values.add(f"{amount}{match.group(2).lower()}")
    return values


def _meaningful_topic_terms(query):
    ignored = {
        "keress", "nekem", "find", "me", "suche", "mir",
        "buy", "kaufen", "price", "prices", "preis",
        "ssd", "solid", "state", "drive",
        "gb", "tb", "eur", "usd",
        "os", "es", "as", "t", "ot", "et", "at",
        "4", "2", "1",
    }
    terms = []
    folded = _fold(query)
    for token in re.findall(r"[a-z0-9]+", folded):
        if token in ignored or token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
    return terms[:6]


def _is_product_specific_url(url):
    if is_generic_shopping_url(url):
        return False

    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False

    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower().rstrip("/")
    query = parse_qs(parsed.query)

    if not host:
        return False
    if any(marker in host for marker in _NON_PRODUCT_HOST_MARKERS):
        return False
    if any(marker in path for marker in _GENERIC_PATH_MARKERS):
        return False
    if path.startswith("/s-") and path.endswith("/k0"):
        return False

    product_path_markers = (
        "/product/",
        "/produkte/",
        "/produkt/",
        "/itm/",
        "/dp/",
        "/p/",
        "/termek/",
        "/productdetail/",
        "/product-details/",
    )
    if any(marker in path for marker in product_path_markers):
        return True

    generic_query_keys = {
        "filter", "filters", "category", "cat", "search", "query", "keyword", "keywords"
    }
    if generic_query_keys.intersection(query):
        return False

    # Fail closed on ambiguous leaf URLs. Search/category/article pages must never
    # be promoted to product evidence merely because their path is non-empty.
    return False


def _title_looks_generic(title):
    folded = _fold(title)
    if not folded:
        return True
    return any(marker in folded for marker in _GENERIC_TITLE_MARKERS)


def _topic_matches(query, item):
    evidence = _fold(" ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
    ]))
    if not evidence:
        return False

    requested_capacities = _capacity_tokens(query)
    if requested_capacities:
        evidence_capacities = _capacity_tokens(evidence)
        if not requested_capacities.intersection(evidence_capacities):
            return False

    folded_query = _fold(query)
    if "ssd" in folded_query and "ssd" not in evidence:
        return False

    topic_terms = _meaningful_topic_terms(query)
    if topic_terms and not any(term in evidence for term in topic_terms):
        # Capacity + explicit product class is already a useful identity match.
        if not (requested_capacities and "ssd" in folded_query and "ssd" in evidence):
            return False

    return True


def _parse_number(value):
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[-1]
        raw = raw.replace(",", ".") if len(tail) <= 2 else raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _prices(text):
    values = []
    patterns = (
        ("EUR", r"€\s*(\d+(?:[.,]\d+)?)"),
        ("EUR", r"\b(\d+(?:[.,]\d+)?)\s*eur\b"),
        ("USD", r"\$\s*(\d+(?:[.,]\d+)?)"),
        ("USD", r"\b(\d+(?:[.,]\d+)?)\s*usd\b"),
    )
    for currency, pattern in patterns:
        for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE):
            value = _parse_number(match.group(1))
            if value is None:
                continue
            pair = (currency, round(value, 2))
            if pair not in values:
                values.append(pair)
    return values


def _verified_price(item):
    identity = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
    ])
    identity_prices = _prices(identity)
    if len(identity_prices) == 1:
        return identity_prices[0]
    if identity_prices:
        return None

    page_prices = _prices(item.get("page_text", ""))
    if len(page_prices) == 1:
        return page_prices[0]
    return None


def build_generic_shopping_records(query, results, limit=6):
    records = []
    seen_urls = set()

    for item in results or []:
        title = " ".join(str(item.get("title", "")).split())
        url = str(item.get("url", "")).strip()
        if not title or not url or url in seen_urls:
            continue
        if not _is_product_specific_url(url):
            continue
        if _title_looks_generic(title):
            continue
        if not _topic_matches(query, item):
            continue

        record = {
            "title": title,
            "url": url,
            "price": _verified_price(item),
        }
        records.append(record)
        seen_urls.add(url)
        if len(records) >= int(limit):
            break

    return records


def render_generic_shopping_answer(user_prompt, records):
    language = detect_user_language(user_prompt)
    records = list(records or [])

    if language == "hu":
        if not records:
            return (
                "Nem találtam olyan termékszintű forrást, amelyből megbízhatóan "
                "ellenőrizhető konkrét terméket tudnék ajánlani. Nem fogok kitalált "
                "árat vagy specifikációt megadni."
            )
        lines = ["Ellenőrzött termékszintű találatok:"]
        for record in records:
            suffix = ""
            price = record.get("price")
            if price:
                currency, value = price
                suffix = f" — {value:.2f} {currency}".replace(".", ",")
            lines.append(
                f"- {record['title']}{suffix} — [forrás]({record['url']})"
            )
        lines.append(
            ""
            "Csak olyan árat tüntettem fel, amelyet a termékszintű forrásból "
            "egyértelműen ellenőrizni lehetett. Hiányzó specifikációkat nem egészítettem ki."
        )
        return "\n".join(lines)

    if language == "de":
        if not records:
            return (
                "Ich habe keine produktspezifische Quelle gefunden, aus der ich ein "
                "konkretes Produkt zuverlässig verifizieren kann. Ich erfinde keine "
                "Preise oder technischen Daten."
            )
        lines = ["Verifizierte produktspezifische Treffer:"]
        for record in records:
            suffix = ""
            price = record.get("price")
            if price:
                currency, value = price
                suffix = f" — {value:.2f} {currency}"
            lines.append(
                f"- {record['title']}{suffix} — [Quelle]({record['url']})"
            )
        lines.append(
            ""
            "Preise werden nur angezeigt, wenn sie aus einer produktspezifischen "
            "Quelle eindeutig verifiziert werden konnten. Fehlende Daten werden nicht ergänzt."
        )
        return "\n".join(lines)

    if not records:
        return (
            "I could not find a product-specific source that reliably verifies a "
            "concrete product. I will not invent prices or specifications."
        )

    lines = ["Verified product-level results:"]
    for record in records:
        suffix = ""
        price = record.get("price")
        if price:
            currency, value = price
            suffix = f" — {value:.2f} {currency}"
        lines.append(
            f"- {record['title']}{suffix} — [source]({record['url']})"
        )
    lines.append(
        ""
        "Prices are shown only when they can be verified unambiguously from a "
        "product-level source. Missing specifications are not filled in."
    )
    return "\n".join(lines)
