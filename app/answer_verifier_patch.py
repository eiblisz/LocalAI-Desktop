import math


def _round_half_up(value):
    return int(math.floor(float(value) + 0.5))


def install_answer_price_equivalence_patch(evidence_verifier):
    if getattr(evidence_verifier, "_answer_price_equivalence_patch_installed", False):
        return

    original_verify = evidence_verifier.verify_answer_against_evidence

    def _is_verified_price_equivalent(answer_price, verified_prices):
        answer_value = round(float(answer_price), 2)

        if any(abs(answer_value - verified) <= 0.01 for verified in verified_prices):
            return True

        # A whole-currency-unit claim may be the ordinary displayed rounding of a
        # VERIFIED cent-precision price. Do not allow arbitrary approximation.
        if abs(answer_value - round(answer_value)) > 0.01:
            return False

        answer_whole = int(round(answer_value))
        return any(
            _round_half_up(verified) == answer_whole
            for verified in verified_prices
        )

    def verify_answer_against_evidence(answer, query, ledgers):
        valid, reasons = original_verify(answer, query, ledgers)
        if valid or "answer_unverified_price" not in reasons:
            return valid, reasons

        plan = evidence_verifier.build_search_plan(query)
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
                price.get("status") == evidence_verifier.VERIFIED
                and isinstance(price.get("value"), (int, float))
            ):
                value = round(float(price["value"]), 2)
                if value not in verified_prices:
                    verified_prices.append(value)

        if not verified_prices:
            return valid, reasons

        answer_prices = evidence_verifier._extract_prices(answer, currency)
        if not answer_prices:
            return valid, reasons

        maximum = round(float(max_price), 2)
        for answer_price in answer_prices:
            value = round(float(answer_price), 2)
            if value > maximum + 0.01:
                return valid, reasons
            if abs(value - maximum) <= 0.01:
                continue
            if not _is_verified_price_equivalent(value, verified_prices):
                return valid, reasons

        narrowed = [
            reason for reason in reasons
            if reason != "answer_unverified_price"
        ]
        return (not narrowed), narrowed

    evidence_verifier.verify_answer_against_evidence = verify_answer_against_evidence
    evidence_verifier._answer_price_equivalence_patch_installed = True
