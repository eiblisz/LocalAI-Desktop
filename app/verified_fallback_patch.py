import threading


_state = threading.local()


def _verified_value(fields, name):
    field = (fields or {}).get(name) or {}
    if field.get("status") != "VERIFIED":
        return None
    return field.get("value")


def _deterministic_verified_answer(worker, ledgers):
    accepted = [
        ledger for ledger in list(ledgers or [])
        if ledger.get("verdict") == "ACCEPT"
    ]
    if not accepted:
        return ""

    hungarian = "Hungarian" in worker._conversation_language_instruction()
    if hungarian:
        lines = [
            "A modell generalt valasza nem ment at az ellenorzesen, ezert csak a host altal VERIFIED bizonyitekokat mutatom:",
            "",
        ]
    else:
        lines = [
            "The model-generated answer did not pass verification, so only host-VERIFIED evidence is shown:",
            "",
        ]

    for index, ledger in enumerate(accepted[:6], start=1):
        fields = ledger.get("fields") or {}
        title = " ".join(str(ledger.get("title") or "Verified product").split())
        url = str(_verified_value(fields, "url") or ledger.get("url") or "").strip()
        exact_kit = _verified_value(fields, "exact_kit")
        memory_type = _verified_value(fields, "memory_type")
        speed = _verified_value(fields, "speed_mhz")
        country = _verified_value(fields, "country")
        price = _verified_value(fields, "price")
        currency = str((ledger.get("plan") or {}).get("currency") or "").strip()

        verified_parts = []
        if exact_kit is not None:
            verified_parts.append(str(exact_kit))
        if memory_type is not None:
            verified_parts.append(str(memory_type).upper())
        if speed is not None:
            verified_parts.append(f"{int(speed)} MHz")
        if country is not None:
            verified_parts.append(str(country))
        if isinstance(price, (int, float)):
            verified_parts.append(f"{float(price):.2f} {currency}".strip())

        lines.append(f"{index}. {title}")
        if verified_parts:
            label = "Ellenorzott adatok" if hungarian else "Verified fields"
            lines.append(f"   {label}: " + " | ".join(verified_parts))
        if url:
            label = "Link" if hungarian else "Link"
            lines.append(f"   {label}: {url}")
        lines.append("")

    return "\n".join(lines).strip()


def install_verified_fallback_patch(workers_module):
    if getattr(workers_module, "_verified_fallback_patch_installed", False):
        return

    original_filter = workers_module.filter_verified_results
    original_safe_failure = workers_module.ChatWebWorker._safe_evidence_failure

    def filter_verified_results(query, results):
        accepted, ledgers, constrained = original_filter(query, results)
        _state.ledgers = list(ledgers or [])
        return accepted, ledgers, constrained

    def safe_evidence_failure(self, answer_rejected=False):
        if answer_rejected:
            fallback = _deterministic_verified_answer(
                self,
                getattr(_state, "ledgers", []),
            )
            if fallback:
                return fallback
        return original_safe_failure(self, answer_rejected=answer_rejected)

    workers_module.filter_verified_results = filter_verified_results
    workers_module.ChatWebWorker._safe_evidence_failure = safe_evidence_failure
    workers_module._verified_fallback_patch_installed = True
