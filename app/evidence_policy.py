import math


class EvidencePolicy:
    """Explicit constrained-shopping evidence policy."""

    @staticmethod
    def authoritative_price(
        text,
        currency,
        label,
        *,
        extract_prices,
        has_lowest_price_marker,
    ):
        prices = extract_prices(text, currency)
        if not prices:
            return None, None
        if len(prices) == 1:
            return prices[0], label
        if has_lowest_price_marker(text):
            return min(prices), f"{label} explicit lowest-price evidence"
        return None, None

    @classmethod
    def apply_price_evidence(
        cls,
        ledger,
        item,
        *,
        extract_prices,
        has_lowest_price_marker,
        field,
        VERIFIED,
        REJECTED,
        UNKNOWN,
    ):
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
        for text, label in (
            (title, "result title"),
            (snippet, "result snippet"),
            (page_text, "fetched page"),
        ):
            price, source = cls.authoritative_price(
                text,
                currency,
                label,
                extract_prices=extract_prices,
                has_lowest_price_marker=has_lowest_price_marker,
            )
            if price is not None:
                break

        fields = ledger.get("fields") or {}
        if price is None:
            seen = (
                extract_prices(title, currency)
                + extract_prices(snippet, currency)
                + extract_prices(page_text, currency)
            )
            unique = []
            for value in seen:
                if value not in unique:
                    unique.append(value)
            fields["price"] = field(
                UNKNOWN,
                unique or None,
                "no unambiguous product-price authority",
            )
        elif price <= float(max_price):
            fields["price"] = field(VERIFIED, price, source)
        else:
            fields["price"] = field(
                REJECTED,
                price,
                f"{source}: above maximum",
            )

        required = list(ledger.get("required") or [])
        rejected = [
            name for name in required
            if (fields.get(name) or {}).get("status") == REJECTED
        ]
        unverified = [
            name for name in required
            if (fields.get(name) or {}).get("status") != VERIFIED
        ]
        ledger["fields"] = fields
        ledger["rejected"] = rejected
        ledger["unverified"] = unverified
        ledger["verdict"] = "ACCEPT" if not unverified else "REJECT"
        return ledger

    @staticmethod
    def _round_half_up(value):
        return int(math.floor(float(value) + 0.5))

    @classmethod
    def is_verified_price_equivalent(cls, answer_price, verified_prices):
        answer_value = round(float(answer_price), 2)
        if any(
            abs(answer_value - verified) <= 0.01
            for verified in verified_prices
        ):
            return True
        if abs(answer_value - round(answer_value)) > 0.01:
            return False
        answer_whole = int(round(answer_value))
        return any(
            cls._round_half_up(verified) == answer_whole
            for verified in verified_prices
        )

    @classmethod
    def reconcile_price_equivalence(
        cls,
        valid,
        reasons,
        answer,
        query,
        ledgers,
        *,
        build_search_plan,
        extract_prices,
        VERIFIED,
    ):
        if valid or "answer_unverified_price" not in reasons:
            return valid, reasons

        plan = build_search_plan(query)
        currency = str(plan.get("currency") or "")
        max_price = plan.get("max_price")
        if not currency or max_price is None:
            return valid, reasons

        accepted = [
            ledger for ledger in ledgers
            if ledger.get("verdict") == "ACCEPT"
        ]
        verified_prices = []
        for ledger in accepted:
            price = (ledger.get("fields") or {}).get("price") or {}
            if (
                price.get("status") == VERIFIED
                and isinstance(price.get("value"), (int, float))
            ):
                value = round(float(price["value"]), 2)
                if value not in verified_prices:
                    verified_prices.append(value)

        if not verified_prices:
            return valid, reasons

        answer_prices = extract_prices(answer, currency)
        if not answer_prices:
            return valid, reasons

        maximum = round(float(max_price), 2)
        for answer_price in answer_prices:
            value = round(float(answer_price), 2)
            if value > maximum + 0.01:
                return valid, reasons
            if abs(value - maximum) <= 0.01:
                continue
            if not cls.is_verified_price_equivalent(
                value,
                verified_prices,
            ):
                return valid, reasons

        narrowed = [
            reason for reason in reasons
            if reason != "answer_unverified_price"
        ]
        return (not narrowed), narrowed
