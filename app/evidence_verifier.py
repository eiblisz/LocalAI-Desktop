import re
import unicodedata
from urllib.parse import urlparse

from .web_search_tool import build_search_plan


VERIFIED = "VERIFIED"
UNKNOWN = "UNKNOWN"
REJECTED = "REJECTED"


def _fold_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    ascii_text = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )
    return " ".join(ascii_text.split())


def _normalize_spec(value):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value or "").lower().replace("×", "x"),
    )


def _extract_kits(text):
    return {
        _normalize_spec(match.group(0))
        for match in re.finditer(
            r"\b\d+\s*[x×]\s*\d+\s*(?:gb|tb)\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    }


def _extract_memory_types(text):
    return {
        _normalize_spec(match.group(0))
        for match in re.finditer(
            r"\bddr\s*[345]\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    }


def _extract_speeds(text):
    values = {
        int(match.group(1))
        for match in re.finditer(
            r"\b(\d{3,5})\s*(?:mhz|mt/s|mts|mtps)\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    }
    values.update(
        int(match.group(1))
        for match in re.finditer(
            r"\bddr[345][\s-]+(\d{3,5})\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )
    return values


def _parse_price_number(value):
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


def _extract_prices(text, currency):
    currency = str(currency or "").upper()
    if not currency:
        return []

    if currency == "EUR":
        patterns = [
            r"€\s*(\d+(?:[.,]\d+)?)",
            r"\beur\s*(\d+(?:[.,]\d+)?)\b",
            r"\b(\d+(?:[.,]\d+)?)\s*eur\b",
        ]
    elif currency == "USD":
        patterns = [
            r"\$\s*(\d+(?:[.,]\d+)?)",
            r"\busd\s*(\d+(?:[.,]\d+)?)\b",
            r"\b(\d+(?:[.,]\d+)?)\s*usd\b",
        ]
    else:
        return []

    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE):
            value = _parse_price_number(match.group(1))
            if value is None:
                continue
            rounded = round(value, 2)
            if rounded not in values:
                values.append(rounded)
    return values


def evidence_required(query_or_plan):
    plan = (
        query_or_plan
        if isinstance(query_or_plan, dict)
        else build_search_plan(query_or_plan)
    )
    return any([
        bool(plan.get("exact_kit")),
        bool(plan.get("memory_type")),
        plan.get("speed_mhz") is not None,
        plan.get("max_price") is not None,
    ])


def _field(status, value=None, evidence=None):
    return {
        "status": status,
        "value": value,
        "evidence": evidence,
    }


def _identity_field(requested, found, label):
    if requested in found and found == {requested}:
        return _field(VERIFIED, requested, label)
    if found:
        return _field(REJECTED, sorted(found), label)
    return _field(UNKNOWN, None, label)


def _speed_field(requested, found, label):
    if int(requested) in found and found == {int(requested)}:
        return _field(VERIFIED, int(requested), label)
    if found:
        return _field(REJECTED, sorted(found), label)
    return _field(UNKNOWN, None, label)


def build_evidence_ledger(query, item):
    plan = build_search_plan(query)
    title = " ".join(str(item.get("title", "")).split())
    snippet = " ".join(str(item.get("snippet", "")).split())
    page_text = " ".join(str(item.get("page_text", "")).split())
    identity_text = " ".join(value for value in [title, snippet] if value)
    url = str(item.get("url", "")).strip()

    fields = {}

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        fields["url"] = _field(VERIFIED, url, "result URL")
    else:
        fields["url"] = _field(REJECTED, url, "invalid result URL")

    requested_kit = str(plan.get("exact_kit") or "")
    if requested_kit:
        fields["exact_kit"] = _identity_field(
            requested_kit,
            _extract_kits(identity_text),
            "result title/snippet identity",
        )

    requested_memory = str(plan.get("memory_type") or "")
    if requested_memory:
        identity_values = _extract_memory_types(identity_text)
        if identity_values:
            fields["memory_type"] = _identity_field(
                requested_memory,
                identity_values,
                "result title/snippet identity",
            )
        else:
            page_values = _extract_memory_types(page_text)
            fields["memory_type"] = _identity_field(
                requested_memory,
                page_values,
                "fetched page",
            )

    requested_speed = plan.get("speed_mhz")
    if requested_speed is not None:
        identity_values = _extract_speeds(identity_text)
        if identity_values:
            fields["speed_mhz"] = _speed_field(
                requested_speed,
                identity_values,
                "result title/snippet identity",
            )
        else:
            page_values = _extract_speeds(page_text)
            fields["speed_mhz"] = _speed_field(
                requested_speed,
                page_values,
                "fetched page",
            )

    if plan.get("country") == "DE":
        host = (parsed.hostname or "").lower()
        folded = _fold_text(identity_text + " " + page_text)
        country_ok = (
            host.endswith(".de")
            or bool(re.search(r"\b(?:germany|deutschland|nemetorszag)\w*\b", folded))
        )
        fields["country"] = _field(
            VERIFIED if country_ok else UNKNOWN,
            "DE" if country_ok else None,
            "result host/text",
        )

    max_price = plan.get("max_price")
    currency = str(plan.get("currency") or "")
    if max_price is not None and currency:
        identity_prices = _extract_prices(identity_text, currency)
        page_prices = _extract_prices(page_text, currency)
        prices = identity_prices if identity_prices else page_prices
        source = "result title/snippet identity" if identity_prices else "fetched page"

        if len(prices) == 1:
            price = prices[0]
            if price <= float(max_price):
                fields["price"] = _field(
                    VERIFIED,
                    price,
                    source,
                )
            else:
                fields["price"] = _field(
                    REJECTED,
                    price,
                    f"{source}: above maximum",
                )
        elif len(prices) > 1:
            fields["price"] = _field(
                UNKNOWN,
                prices,
                f"{source}: ambiguous multiple prices",
            )
        else:
            fields["price"] = _field(
                UNKNOWN,
                None,
                "no product-specific price evidence",
            )

    required = ["url"]
    if requested_kit:
        required.append("exact_kit")
    if requested_memory:
        required.append("memory_type")
    if requested_speed is not None:
        required.append("speed_mhz")
    if plan.get("country") == "DE":
        required.append("country")
    if max_price is not None and currency:
        required.append("price")

    rejected = [
        name for name in required
        if fields.get(name, {}).get("status") == REJECTED
    ]
    unverified = [
        name for name in required
        if fields.get(name, {}).get("status") != VERIFIED
    ]

    return {
        "query": query,
        "title": title,
        "url": url,
        "plan": plan,
        "fields": fields,
        "required": required,
        "rejected": rejected,
        "unverified": unverified,
        "verdict": "ACCEPT" if not unverified else "REJECT",
    }


def filter_verified_results(query, results):
    plan = build_search_plan(query)
    if not evidence_required(plan):
        return list(results), [], False

    accepted = []
    ledgers = []
    for item in results:
        ledger = build_evidence_ledger(query, item)
        ledgers.append(ledger)
        if ledger["verdict"] == "ACCEPT":
            copy = dict(item)
            copy["evidence_ledger"] = ledger
            accepted.append(copy)

    return accepted, ledgers, True


def evidence_ledger_context_text(payload):
    lines = [
        "VERIFIED WEB EVIDENCE LEDGER",
        f"Provider: {payload.get('provider', '')}",
        f"Query: {payload.get('query', '')}",
        "Use ONLY fields marked VERIFIED below. Do not infer missing details.",
    ]

    for index, item in enumerate(payload.get("results") or [], start=1):
        ledger = item.get("evidence_ledger") or {}
        fields = ledger.get("fields") or {}
        lines.extend([
            "",
            f"RESULT {index}",
            f"Title: {ledger.get('title') or item.get('title', '')}",
            f"URL: {ledger.get('url') or item.get('url', '')}",
            "Verdict: ACCEPT",
        ])

        exact_kit = fields.get("exact_kit")
        if exact_kit and exact_kit.get("status") == VERIFIED:
            lines.append(f"Exact kit: {exact_kit.get('value')} [VERIFIED]")

        memory_type = fields.get("memory_type")
        if memory_type and memory_type.get("status") == VERIFIED:
            lines.append(f"Memory type: {memory_type.get('value')} [VERIFIED]")

        speed = fields.get("speed_mhz")
        if speed and speed.get("status") == VERIFIED:
            lines.append(f"Speed: {speed.get('value')} MHz [VERIFIED]")

        country = fields.get("country")
        if country and country.get("status") == VERIFIED:
            lines.append(f"Country: {country.get('value')} [VERIFIED]")

        price = fields.get("price")
        if price and price.get("status") == VERIFIED:
            currency = str((ledger.get("plan") or {}).get("currency") or "")
            lines.append(
                f"Price: {float(price.get('value')):.2f} {currency} [VERIFIED]"
            )

    return "\n".join(lines).strip()


def verify_answer_against_evidence(answer, query, ledgers):
    text = str(answer or "")
    plan = build_search_plan(query)
    if not evidence_required(plan):
        return True, []

    accepted = [ledger for ledger in ledgers if ledger.get("verdict") == "ACCEPT"]
    if not accepted:
        return False, ["no_accepted_evidence"]

    reasons = []

    requested_kit = str(plan.get("exact_kit") or "")
    if requested_kit:
        found = _extract_kits(text)
        if any(value != requested_kit for value in found):
            reasons.append("answer_exact_kit_mismatch")

    requested_memory = str(plan.get("memory_type") or "")
    if requested_memory:
        found = _extract_memory_types(text)
        if any(value != requested_memory for value in found):
            reasons.append("answer_memory_type_mismatch")

    requested_speed = plan.get("speed_mhz")
    if requested_speed is not None:
        found = _extract_speeds(text)
        if any(value != int(requested_speed) for value in found):
            reasons.append("answer_speed_mismatch")

    allowed_urls = {
        str(ledger.get("url") or "").strip()
        for ledger in accepted
        if str(ledger.get("url") or "").strip()
    }
    found_urls = set(re.findall(r"https?://[^\s)\]>]+", text))
    for url in found_urls:
        clean = url.rstrip(".,;:")
        if clean not in allowed_urls:
            reasons.append("answer_unverified_url")
            break

    max_price = plan.get("max_price")
    currency = str(plan.get("currency") or "")
    if max_price is not None and currency:
        answer_prices = _extract_prices(text, currency)
        verified_prices = []
        for ledger in accepted:
            price = (ledger.get("fields") or {}).get("price") or {}
            if price.get("status") == VERIFIED and isinstance(price.get("value"), (int, float)):
                verified_prices.append(round(float(price["value"]), 2))

        allowed_prices = set(verified_prices)
        allowed_prices.add(round(float(max_price), 2))
        for price in answer_prices:
            if price > float(max_price) + 0.01:
                reasons.append("answer_price_above_max")
                break
            if not any(abs(price - allowed) <= 0.01 for allowed in allowed_prices):
                reasons.append("answer_unverified_price")
                break

    if accepted and not found_urls:
        product_claim = bool(
            _extract_kits(text)
            or _extract_memory_types(text)
            or _extract_speeds(text)
            or _extract_prices(text, currency)
        )
        if product_claim:
            reasons.append("answer_missing_verified_url")

    return (not reasons), list(dict.fromkeys(reasons))
