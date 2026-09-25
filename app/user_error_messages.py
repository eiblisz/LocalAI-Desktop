"""Safe public wording for internal execution failures.

The original exception remains available to request traces and diagnostic
metadata.  This module prevents implementation details from leaking to Desktop
or Discord users.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicError:
    code: str
    message: str


def public_error(message, *, language="hu"):
    raw = " ".join(str(message or "").split())
    lowered = raw.casefold()
    hungarian = str(language or "hu") == "hu"

    if "grounded answer" in lowered or "unsupported factual literals" in lowered:
        return PublicError(
            "grounding_verification_failed",
            (
                "Az ellenőrzött források alapján most nem tudok biztonságos "
                "választ adni. Próbáld meg egy rövid, pontos kérdéssel újra."
                if hungarian else
                "I could not verify a safe answer from the available sources. Please try a shorter, more specific question."
            ),
        )
    if "no usable public sources" in lowered:
        return PublicError(
            "no_usable_public_sources",
            (
                "Most nem találtam elég megbízható nyilvános forrást a válaszhoz. "
                "Próbáld meg később vagy pontosabb kulcsszavakkal."
                if hungarian else
                "I could not find enough reliable public sources for this answer. Please try again later or use more specific keywords."
            ),
        )
    if "output-token limit" in lowered or "output token limit" in lowered:
        return PublicError(
            "generation_length_limit",
            (
                "A válasz elérte a biztonságos kimeneti korlátot, ezért nem jelenítek meg csonka szöveget. Próbáld meg rövidebb kéréssel."
                if hungarian else
                "The response reached its safe output limit, so I did not show a truncated answer. Please try a shorter request."
            ),
        )
    if "language_repair_failed" in lowered:
        return PublicError(
            "language_repair_failed",
            (
                "A válasz nyelvi hibáját most nem sikerült biztonságosan javítani. Próbáld meg újra."
                if hungarian else
                "I could not safely repair a language issue in the response. Please try again."
            ),
        )
    if "repair_integrity_failed" in lowered:
        return PublicError(
            "repair_integrity_failed",
            (
                "A válasz javítása megváltoztatta volna a védett tartalmat, ezért elutasítottam. Próbáld meg újra."
                if hungarian else
                "The repair would have changed protected response content, so it was rejected. Please try again."
            ),
        )
    return PublicError(
        "execution_failed",
        (
            "A kérés feldolgozása most nem sikerült. Próbáld meg újra."
            if hungarian else
            "The request could not be completed right now. Please try again."
        ),
    )
