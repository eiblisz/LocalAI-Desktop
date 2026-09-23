import pytest

from app.grounded_factual_guard import (
    GroundedFactualGuardError,
    guard_grounded_answer,
    unsupported_grounded_literals,
)


class RepairClient:
    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = 0

    def chat_once(self, model, messages, timeout=600.0, **kwargs):
        self.calls += 1
        return self.repaired


def test_grounded_guard_detects_unsupported_year_and_name():
    authority = (
        "USER REQUEST: Mikor készült a Csillag Története?\n"
        "AUTHORIZED EVIDENCE: A forrás szerint Example Author készítette 1912-ben."
    )

    unsupported = unsupported_grounded_literals(
        "Other Person készítette 1956-ban.",
        authority,
    )

    assert "1956" in unsupported
    assert "Other Person" in unsupported


def test_grounded_guard_accepts_supported_factual_literals():
    authority = (
        "AUTHORIZED EVIDENCE: Example Author készítette 1912-ben. "
        "Forrás: https://example.com/source"
    )

    unsupported = unsupported_grounded_literals(
        "Example Author készítette 1912-ben. https://example.com/source",
        authority,
    )

    assert unsupported == ()


def test_grounded_guard_canonicalizes_an_unsupported_middle_name_without_repair():
    authority = "AUTHORIZED EVIDENCE: Sample Musician is an artist."
    client = RepairClient("should not be used")

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Ki Sample Musician?",
        "Sample Middle Musician is an artist.",
        authority,
    )

    assert result == "Sample Musician is an artist."
    assert client.calls == 0


def test_grounded_guard_repairs_false_premise_once():
    authority = (
        "USER REQUEST: Mikor írta Wrong Author a Silver Storyt?\n"
        "AUTHORIZED EVIDENCE: Silver Story szerzője Correct Author, 1912."
    )
    client = RepairClient("A Silver Story szerzője Correct Author, 1912.")

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Mikor írta Wrong Author a Silver Storyt?",
        "Wrong Author 1956-ban írta.",
        authority,
    )

    assert result == "A Silver Story szerzője Correct Author, 1912."
    assert client.calls == 1


def test_grounded_guard_fails_closed_after_bad_repair():
    authority = "AUTHORIZED EVIDENCE: Correct Author, 1912."
    client = RepairClient("Other Person 1956-ban írta.")

    with pytest.raises(GroundedFactualGuardError):
        guard_grounded_answer(
            client,
            "qwen-test",
            "Mikor írták?",
            "Wrong Author 1956-ban írta.",
            authority,
        )

    assert client.calls == 1



def test_factual_risk_force_verify_checks_relation_even_when_literals_are_known():
    authority = (
        "USER REQUEST: Did Wrong Author write Silver Story in 1912?\n"
        "AUTHORIZED EVIDENCE: Silver Story was written by Correct Author in 1912."
    )
    client = RepairClient(
        "No. Silver Story was written by Correct Author in 1912, not Wrong Author."
    )

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Did Wrong Author write Silver Story in 1912?",
        "Yes. Wrong Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
    )

    assert result.startswith("No.")
    assert client.calls == 1



def test_grounded_guard_strips_unsupported_source_attribution_but_keeps_supported_fact():
    authority = (
        "USER REQUEST: Ki írta a Silver Storyt és mikor?\n"
        "AUTHORIZED EVIDENCE: Silver Story szerzője Correct Author, 1912."
    )
    client = RepairClient(
        "A Magyar Könyvszemle egyik cikke szerint Correct Author írta "
        "a Silver Storyt 1912-ben."
    )

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Ki írta a Silver Storyt és mikor?",
        "Wrong Author írta 1956-ban.",
        authority,
        force_verify=True,
    )

    assert "Magyar Könyvszemle" not in result
    assert "Correct Author" in result
    assert "1912" in result
    assert client.calls == 1


def test_grounded_guard_still_rejects_unsupported_relation_name_not_source_attribution():
    authority = (
        "USER REQUEST: Ki írta a Silver Storyt?\n"
        "AUTHORIZED EVIDENCE: Silver Story szerzője Correct Author."
    )
    client = RepairClient("Other Person írta a Silver Storyt.")

    with pytest.raises(GroundedFactualGuardError):
        guard_grounded_answer(
            client,
            "qwen-test",
            "Ki írta a Silver Storyt?",
            "Wrong Author írta a Silver Storyt.",
            authority,
            force_verify=True,
        )



def test_grounded_repair_prompt_preserves_evidence_name_form_and_order():
    class CaptureClient:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.messages = messages
            return "Correct Author írta a Silver Storyt 1912-ben."

    client = CaptureClient()
    authority = (
        "USER REQUEST: Ki írta a Silver Storyt?\n"
        "AUTHORIZED EVIDENCE: Correct Author írta a Silver Storyt 1912-ben."
    )

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Ki írta a Silver Storyt?",
        "Wrong Author írta 1956-ban.",
        authority,
        force_verify=True,
    )

    assert result == "Correct Author írta a Silver Storyt 1912-ben."
    system = client.messages[0]["content"]
    assert "Preserve proper-name spelling, diacritics, and token order" in system
    assert "use the form conventional in the requested answer language" in system



def test_grounded_guard_matches_accented_and_unaccented_name_literals():
    authority = (
        "USER REQUEST: Mikor írta Arany Janos a Silver Storyt?\n"
        "AUTHORIZED EVIDENCE: Arany Janos nem a szerző; Correct Author írta 1912-ben."
    )

    unsupported = unsupported_grounded_literals(
        "Arany János nem írta a Silver Storyt; Correct Author írta 1912-ben.",
        authority,
    )

    assert unsupported == ()



def test_grounded_guard_accepts_accented_name_when_ascii_form_is_in_full_authority_text():
    authority = (
        "USER REQUEST:\n"
        "Mikor írta Arany Janos a Janos vitez cimu verset?\n\n"
        "AUTHORIZED EVIDENCE:\n"
        "Petőfi Sándor: János vitéz. 1844."
    )

    unsupported = unsupported_grounded_literals(
        "A János vitézt nem Arany János, hanem Petőfi Sándor írta 1844-ben.",
        authority,
    )

    assert "Arany János" not in unsupported
    assert unsupported == ()


def test_grounded_guard_still_rejects_new_name_absent_from_full_authority_text():
    authority = (
        "USER REQUEST:\n"
        "Mikor írta Arany Janos a Janos vitez cimu verset?\n\n"
        "AUTHORIZED EVIDENCE:\n"
        "Petőfi Sándor: János vitéz. 1844."
    )

    unsupported = unsupported_grounded_literals(
        "A művet Arany János helyett Kitalált Szerző írta 1844-ben.",
        authority,
    )

    assert "Kitalált Szerző" in unsupported
