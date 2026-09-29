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


def test_grounded_guard_accepts_hungarian_case_suffix_on_supported_entity():
    authority = (
        "AUTHORIZED EVIDENCE: A Kisfaludy Társaság pályázatot hirdetett."
    )

    unsupported = unsupported_grounded_literals(
        "A Kisfaludy Társaságnál meghirdetett pályázat fontos volt.",
        authority,
    )

    assert unsupported == ()


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


def test_grounded_guard_records_remaining_unsupported_literals_on_failure():
    class Trace:
        def __init__(self):
            self.metadata = {}

        def begin(self, _name):
            pass

        def end(self, _name, **kwargs):
            self.metadata.update(kwargs)

        def add_metadata(self, **kwargs):
            self.metadata.update(kwargs)

    authority = "AUTHORIZED EVIDENCE: Correct Author, 1912."
    client = RepairClient("Other Person 1956-ban írta.")
    trace = Trace()

    with pytest.raises(GroundedFactualGuardError):
        guard_grounded_answer(
            client,
            "qwen-test",
            "Mikor írták?",
            "Wrong Author 1956-ban írta.",
            authority,
            trace=trace,
            force_verify=True,
        )

    assert trace.metadata["factual_guard_force_verify"] is True
    assert "Other Person" in trace.metadata[
        "factual_guard_remaining_unsupported_literals"
    ]
    assert "1956" in trace.metadata[
        "factual_guard_remaining_unsupported_literals"
    ]
    assert trace.metadata["factual_guard_repair_status"] == "unsupported_literals"


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


def test_grounded_guard_accepts_safe_hungarian_inflection_of_evidence_name():
    authority = "AUTHORIZED EVIDENCE: Petőfi Sándor wrote the poem in 1844."

    unsupported = unsupported_grounded_literals(
        "Petőfi Sándort az evidence szerzőjeként említi 1844.",
        authority,
    )

    assert unsupported == ()


def test_grounded_guard_removes_adjacent_duplicate_name_token_before_checking():
    authority = "AUTHORIZED EVIDENCE: Sample Author wrote the work in 1912."
    client = RepairClient("must not be used")

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Who wrote the work?",
        "Sample Sample Author wrote the work in 1912.",
        authority,
    )

    assert result == "Sample Author wrote the work in 1912."
    assert client.calls == 0


def test_grounded_guard_rejects_invented_single_word_quoted_title():
    authority = (
        'USER REQUEST: Mikor jelent meg az első album?\n'
        'AUTHORIZED EVIDENCE: The self-titled debut album was released in 1984.'
    )

    unsupported = unsupported_grounded_literals(
        'A "Mystery" című album 1979-ben jelent meg.',
        authority,
    )

    assert "Mystery" in unsupported
    assert "1979" in unsupported



def test_grounded_guard_repair_uses_explicit_factual_sampling_controls():
    authority = "AUTHORIZED EVIDENCE: Sample Band released its debut album in 1984."

    class SamplingRepairClient:
        def __init__(self):
            self.kwargs = None

        def chat_once(self, **kwargs):
            self.kwargs = dict(kwargs)
            return "Sample Band released its debut album in 1984."

    client = SamplingRepairClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "When did Sample Band release its debut album?",
        "Sample Band released its debut album in 1979.",
        authority,
        force_verify=True,
        output_budget=384,
        temperature=0.0,
        seed=42,
    )

    assert result == "Sample Band released its debut album in 1984."
    assert client.kwargs["num_predict"] == 384
    assert client.kwargs["temperature"] == 0.0
    assert client.kwargs["seed"] == 42



def test_grounded_guard_keeps_supported_extra_context_and_repairs_only_unsupported_detail():
    authority = (
        'USER REQUEST: Melyik nagylemez volt az első a sampleband zenekarnak?\n'
        'AUTHORIZED EVIDENCE: Sample Band released its self-titled debut album '
        'in 1984. The album includes the track "Real Track".'
    )
    draft = (
        'A Sample Band első nagylemeze a saját nevét viselő album volt 1984-ben. '
        'Az albumon szerepel a "Real Track" és a "Fake Track" is.'
    )

    unsupported = unsupported_grounded_literals(draft, authority)
    assert "Fake Track" in unsupported
    assert "Real Track" not in unsupported

    repaired = (
        'A Sample Band első nagylemeze a saját nevét viselő album volt 1984-ben. '
        'Az albumon szerepel a "Real Track" is.'
    )
    client = RepairClient(repaired)

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Melyik nagylemez volt az első a sampleband zenekarnak?",
        draft,
        authority,
        temperature=0.0,
        seed=42,
    )

    assert result == repaired
    assert client.calls == 1


def test_grounded_guard_can_validate_literals_against_full_generation_authority():
    compact_authority = (
        "AUTHORIZED EVIDENCE: A forrás a szabadságharc általános leírását tartalmazza."
    )
    full_generation_authority = (
        compact_authority
        + " Kossuth Lajos a magyar politikai vezetők egyike volt 1848-ban."
    )
    client = RepairClient("must not be used")

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj esszét az 1848-as szabadságharcról.",
        "Kossuth Lajos szerepet vállalt az eseményekben 1848-ban.",
        compact_authority,
        literal_authority_text=full_generation_authority,
    )

    assert "Kossuth Lajos" in result
    assert "1848" in result
    assert client.calls == 0


def test_grounded_guard_still_rejects_literal_absent_from_full_generation_authority():
    compact_authority = "AUTHORIZED EVIDENCE: Correct Author, 1912."
    full_generation_authority = compact_authority + " Additional grounded context."
    client = RepairClient("Other Person 1956-ban írta.")

    with pytest.raises(GroundedFactualGuardError):
        guard_grounded_answer(
            client,
            "qwen-test",
            "Mikor írták?",
            "Wrong Author 1956-ban írta.",
            compact_authority,
            literal_authority_text=full_generation_authority,
        )


def test_long_form_guard_can_prune_one_unsupported_sentence_without_model_repair():
    authority = (
        "AUTHORIZED EVIDENCE: Kossuth Lajos fontos szereplő volt 1848-ban. "
        "A szabadságharc 1849-ben ért véget."
    )
    client = RepairClient("must not be used")
    draft = (
        "Kossuth Lajos fontos szereplő volt 1848-ban. "
        "A Kitalált Személy 1847-ben döntő szerepet játszott. "
        "A szabadságharc 1849-ben ért véget."
    )

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj esszét az 1848-as szabadságharcról.",
        draft,
        authority,
        prune_unsupported_sentences=True,
    )

    assert "Kossuth Lajos" in result
    assert "1849" in result
    assert "Kitalált Személy" not in result
    assert "1847" not in result
    assert client.calls == 0


def test_direct_fact_guard_does_not_prune_unsupported_sentence_by_default():
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


def test_long_form_force_verify_uses_full_repair_authority_after_pruning():
    compact_authority = (
        "AUTHORIZED EVIDENCE: Pákozd and Schwechat are named historical events."
    )
    full_authority = (
        "AUTHORIZED EVIDENCE: Pákozd was a Hungarian victory on 29 September 1848. "
        "Schwechat was fought later, on 30 October 1848."
    )

    class AuditClient:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.messages = messages
            return (
                "A pákozdi ütközet 1848. szeptember 29-én magyar győzelemmel zárult. "
                "A schwechati csatára később, október 30-án került sor."
            )

    client = AuditClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj történelmi esszét.",
        (
            "A Kitalált Birodalom döntötte el a harcot. "
            "A schwechati csata volt az első nagy magyar győzelem."
        ),
        compact_authority,
        force_verify=True,
        literal_authority_text=full_authority,
        repair_authority_text=full_authority,
        prune_unsupported_sentences=True,
    )

    assert "Kitalált Birodalom" not in result
    assert "pákozdi" in result.casefold()
    assert "schwechati" in result.casefold()
    assert "first" not in result.casefold()
    assert "első nagy magyar győzelem" not in result.casefold()
    assert full_authority in client.messages[-1]["content"]


def test_long_form_post_repair_prunes_reintroduced_unsupported_literals():
    authority = (
        "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912. "
        "The work was published in the same year."
    )
    class RepairThenAuditClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "This audit response is malformed."
            if self.calls == 2:
                return (
                    "Correct Author wrote Silver Story in 1912. "
                    "Other Person later changed it in 1956."
                )
            return "S0|KEEP|Correct Author wrote Silver Story in 1912."

    client = RepairThenAuditClient()

    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj rövid ismertetőt a Silver Storyról.",
        "Wrong Author wrote Silver Story in 1956.",
        authority,
        force_verify=True,
        prune_unsupported_sentences=True,
        strict_relation_audit=True,
    )

    assert "Correct Author" in result
    assert "1912" in result
    assert "Other Person" not in result
    assert "1956" not in result
    assert client.calls == 3


def test_malformed_sentence_audit_is_never_reused_as_user_answer():
    authority = (
        "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912. "
        "The work was published in the same year."
    )

    class SequenceClient:
        def __init__(self):
            self.calls = []

        def chat_once(self, **kwargs):
            self.calls.append(dict(kwargs))
            if len(self.calls) == 1:
                return (
                    "The sentences directly quote key facts from the authorized evidence. "
                    "All factual claims are supported."
                )
            if len(self.calls) == 2:
                return (
                    "Correct Author wrote Silver Story in 1912. "
                    "The work was published in the same year."
                )
            return (
                "S0\tKEEP\tCorrect Author wrote Silver Story in 1912.\n"
                "S1\tKEEP\tThe work was published in the same year."
            )

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj ismertetőt a Silver Storyról.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result.startswith("Correct Author wrote Silver Story")
    assert "The sentences directly quote" not in result
    assert len(client.calls) == 3
    assert client.calls[0]["call_phase"] == "factual_sentence_support_audit"
    assert client.calls[1]["call_phase"] == "factual_guard_repair"
    assert client.calls[2]["call_phase"] == "factual_sentence_support_audit"


def test_strict_relation_audit_instruction_rejects_name_cooccurrence_as_support():
    authority = (
        "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912."
    )

    class CaptureClient:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.messages = messages
            return "S0|KEEP|Correct Author wrote Silver Story in 1912."

    client = CaptureClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        strict_relation_audit=True,
    )

    assert result == "Correct Author wrote Silver Story in 1912."
    system = client.messages[0]["content"]
    assert "Mere co-occurrence of the same names is not support." in system
    assert "delete that sentence rather than guessing" in system


def test_sentence_support_gate_does_not_return_heading_only_shell_for_exact_paragraph_request():
    authority = (
        "AUTHORIZED EVIDENCE: Sample event began in 1912. "
        "It continued through the following year."
    )

    class SequenceClient:
        def __init__(self):
            self.calls = 0
            self.messages = []

        def chat_once(self, **kwargs):
            self.calls += 1
            self.messages.append(kwargs["messages"])
            if self.calls == 1:
                return "S0|DROP|-\nS1|DROP|-"
            if self.calls == 2:
                return "\n\n".join(
                    "Sample event began in 1912."
                    for _index in range(10)
                )
            return "\n".join(
                f"S{index}|KEEP|Sample event began in 1912."
                for index in range(10)
            )

    draft = (
        "### Történelmi esszé\n\n"
        "#### 1. Első rész\n\nSample event began in 1912.\n\n"
        "#### 2. Második rész\n\nIt continued through the following year."
    )
    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj egy 10 bekezdésből álló történelmi esszét.",
        draft,
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        prune_unsupported_sentences=True,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert "### Történelmi esszé" not in result
    assert len([block for block in result.split("\n\n") if block.strip()]) == 10
    assert client.calls == 3
    repair_system = client.messages[1][0]["content"]
    assert "exactly 10 substantive prose paragraphs" in repair_system
    assert "Headings are optional and do not count as paragraphs" in repair_system


def test_sentence_support_gate_accepts_literal_tab_placeholder_protocol():
    authority = "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912."

    class PlaceholderClient:
        def chat_once(self, **kwargs):
            return r"S0\<TAB>KEEP\<TAB>Correct Author wrote Silver Story in 1912."

    result = guard_grounded_answer(
        PlaceholderClient(),
        "qwen-test",
        "Írj ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result == "Correct Author wrote Silver Story in 1912."


def test_sentence_support_gate_drops_relation_not_directly_supported():
    authority = (
        "AUTHORIZED EVIDENCE: Ferdinand I was Franz Joseph's uncle. "
        "Franz Joseph became emperor in December 1848."
    )

    class GateClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.calls += 1
            return (
                "S0\tDROP\t-\n"
                "S1\tKEEP\tFranz Joseph became emperor in December 1848."
            )

    client = GateClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj történelmi ismertetőt.",
        (
            "Ferdinand I was Franz Joseph's father. "
            "Franz Joseph became emperor in December 1848."
        ),
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        prune_unsupported_sentences=True,
        strict_relation_audit=True,
        temperature=0.0,
        seed=42,
    )

    assert "father" not in result
    assert "December 1848" in result
    assert client.calls == 1


def test_sentence_support_gate_uses_compact_reference_budget_and_named_call_phase():
    authority = "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912."

    class BudgetClient:
        def __init__(self):
            self.kwargs = None

        def chat_once(self, **kwargs):
            self.kwargs = dict(kwargs)
            return "S0\tKEEP\tCorrect Author wrote Silver Story in 1912."

    client = BudgetClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj hosszú ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result == "Correct Author wrote Silver Story in 1912."
    assert client.kwargs["num_predict"] == 384
    assert client.kwargs["call_phase"] == "factual_sentence_support_audit"
    audit_prompt = client.kwargs["messages"][1]["content"]
    assert "NUMBERED AUTHORIZED EVIDENCE:" in audit_prompt
    assert "E0:" in audit_prompt


def test_sentence_support_gate_accepts_compact_evidence_reference():
    authority = "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912."

    class ReferenceClient:
        def __init__(self):
            self.kwargs = None

        def chat_once(self, **kwargs):
            self.kwargs = dict(kwargs)
            return "S0|KEEP|E0"

    client = ReferenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result == "Correct Author wrote Silver Story in 1912."
    assert "S0|KEEP|E0" not in result
    assert "NEVER copy evidence text" in client.kwargs["messages"][0]["content"]


def test_sentence_support_gate_rejects_unknown_compact_evidence_reference():
    authority = "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912."

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "S0|KEEP|E999"
            if self.calls == 2:
                return "Correct Author wrote Silver Story in 1912."
            return "S0|KEEP|E0"

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result == "Correct Author wrote Silver Story in 1912."
    assert client.calls == 3


def test_sentence_support_gate_rejects_url_only_keep_evidence():
    authority = (
        "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912. "
        "Source: https://example.com/history"
    )

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "S0\tKEEP\thttps://example.com/history"
            if self.calls == 2:
                return "Correct Author wrote Silver Story in 1912."
            return "S0\tKEEP\tCorrect Author wrote Silver Story in 1912."

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj ismertetőt.",
        "Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert result == "Correct Author wrote Silver Story in 1912."
    assert client.calls == 3


def test_sentence_support_gate_requires_explicit_exclusivity_relation():
    authority = (
        "AUTHORIZED EVIDENCE: Sample State intervened in support of Partner State in 1912."
    )

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    "S0\tKEEP\tSample State intervened in support of Partner State in 1912."
                )
            if self.calls == 2:
                return "Sample State 1912-ben beavatkozott Partner State támogatására."
            return (
                "S0\tKEEP\tSample State intervened in support of Partner State in 1912."
            )

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj történelmi ismertetőt.",
        "Sample State volt az egyetlen komoly szövetséges, és 1912-ben beavatkozott.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert "egyetlen" not in result.casefold()
    assert client.calls == 3


def test_sentence_support_gate_rejects_wrong_month_relation():
    authority = "AUTHORIZED EVIDENCE: The event began in September 1912."

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "S0\tKEEP\tThe event began in September 1912."
            if self.calls == 2:
                return "Az esemény 1912 szeptemberében kezdődött."
            return "S0\tKEEP\tThe event began in September 1912."

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj történelmi ismertetőt.",
        "Az esemény 1912 júniusában kezdődött.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert "június" not in result.casefold()
    assert "szeptember" in result.casefold()
    assert client.calls == 3


def test_post_repair_relation_audit_drops_reintroduced_false_speech_attribution():
    authority = (
        "AUTHORIZED EVIDENCE: Sample Poet wrote National Song in 1912. "
        "Sample Politician gave major political speeches in the same period."
    )

    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat_once(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "This draft needs repair."
            if self.calls == 2:
                return (
                    "Sample Politician híres beszédei közé tartozott a National Song. "
                    "Sample Poet wrote National Song in 1912."
                )
            return (
                "S0\tDROP\t-\n"
                "S1\tKEEP\tSample Poet wrote National Song in 1912."
            )

    client = SequenceClient()
    result = guard_grounded_answer(
        client,
        "qwen-test",
        "Írj történelmi ismertetőt.",
        "Sample Politician híres beszédei közé tartozott a National Song.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        prune_unsupported_sentences=True,
        strict_relation_audit=True,
        output_budget=2048,
        temperature=0.0,
        seed=42,
    )

    assert "Sample Politician híres beszédei" not in result
    assert "Sample Poet wrote National Song in 1912." in result
    assert client.calls == 3


def test_sentence_support_gate_requires_evidence_fragment_to_exist_in_authority():
    authority = (
        "AUTHORIZED EVIDENCE: Correct Author wrote Silver Story in 1912. "
        "Other Person was born in 1956."
    )

    class GateClient:
        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            return (
                "S0\tKEEP\tInvented support fragment that is not in evidence.\n"
                "S1\tKEEP\tCorrect Author wrote Silver Story in 1912."
            )

    result = guard_grounded_answer(
        GateClient(),
        "qwen-test",
        "Írj kétmondatos ismertetőt.",
        "Other Person wrote it in 1956. Correct Author wrote Silver Story in 1912.",
        authority,
        force_verify=True,
        literal_authority_text=authority,
        repair_authority_text=authority,
        prune_unsupported_sentences=True,
        strict_relation_audit=True,
    )

    assert "Other Person" not in result
    assert "1956" not in result
    assert "Correct Author" in result
    assert "1912" in result
