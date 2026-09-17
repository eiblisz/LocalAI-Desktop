def _authoritative_price(evidence_verifier, text, currency, label):
    prices = evidence_verifier._extract_prices(text, currency)
    if not prices:
        return None, None

    if len(prices) == 1:
        return prices[0], label

    if evidence_verifier._has_lowest_price_marker(text):
        return min(prices), f"{label} explicit lowest-price evidence"

    return None, None


def install_price_evidence_patch(evidence_verifier):
    if getattr(evidence_verifier, "_price_evidence_patch_installed", False):
        return

    original_build = evidence_verifier.build_evidence_ledger

    def build_evidence_ledger(query, item):
        ledger = original_build(query, item)
        plan = ledger.get("plan") or {}
        max_price = plan.get("max_price")
        currency = str(plan.get("currency") or "")
        if max_price is None or not currency:
            return ledger

        title = " ".join(str(item.get("title", "")).split())
        snippet = " ".join(str(item.get("snippet", "")).split())
        page_text = " ".join(str(item.get("page_text", "")).split())

        price = None
        source = None

        price, source = _authoritative_price(
            evidence_verifier,
            title,
            currency,
            "result title",
        )
        if price is None:
            price, source = _authoritative_price(
                evidence_verifier,
                snippet,
                currency,
                "result snippet",
            )
        if price is None:
            price, source = _authoritative_price(
                evidence_verifier,
                page_text,
                currency,
                "fetched page",
            )

        fields = ledger.get("fields") or {}
        if price is None:
            seen = (
                evidence_verifier._extract_prices(title, currency)
                + evidence_verifier._extract_prices(snippet, currency)
                + evidence_verifier._extract_prices(page_text, currency)
            )
            unique = []
            for value in seen:
                if value not in unique:
                    unique.append(value)
            fields["price"] = evidence_verifier._field(
                evidence_verifier.UNKNOWN,
                unique or None,
                "no unambiguous product-price authority",
            )
        elif price <= float(max_price):
            fields["price"] = evidence_verifier._field(
                evidence_verifier.VERIFIED,
                price,
                source,
            )
        else:
            fields["price"] = evidence_verifier._field(
                evidence_verifier.REJECTED,
                price,
                f"{source}: above maximum",
            )

        required = list(ledger.get("required") or [])
        rejected = [
            name for name in required
            if (fields.get(name) or {}).get("status") == evidence_verifier.REJECTED
        ]
        unverified = [
            name for name in required
            if (fields.get(name) or {}).get("status") != evidence_verifier.VERIFIED
        ]
        ledger["fields"] = fields
        ledger["rejected"] = rejected
        ledger["unverified"] = unverified
        ledger["verdict"] = "ACCEPT" if not unverified else "REJECT"
        return ledger

    evidence_verifier.build_evidence_ledger = build_evidence_ledger
    evidence_verifier._price_evidence_patch_installed = True
