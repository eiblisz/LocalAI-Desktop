import json
import inspect

import pytest

from app.language_policy import (
    hungarian_output_quality_evidence,
    hungarian_output_quality_issues,
    repair_preserves_response_shape,
)
from app.request_trace import RequestTrace
from app.response_guard import (
    FluencyAuditFailed,
    LanguageRepairFailed,
    RepairIntegrityFailed,
    guard_response,
    validate_response,
)
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker
from app.ollama_client import ollama_failure_metadata


def _audit_segments(messages):
    return json.loads(messages[1]["content"].split(
        "USER-VISIBLE RESPONSE SEGMENTS TO AUDIT:\n", 1
    )[1])


def _passing_fluency_audit(messages):
    return json.dumps({
        "judgments": [[item["id"], "pass"] for item in _audit_segments(messages)],
    })


class EditorialRepairClient:
    supports_hungarian_fluency_audit = True

    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        if "Hungarian fluency classifier" in messages[0]["content"]:
            return _passing_fluency_audit(messages)
        return self.repaired


class SingleGenerationClient:
    supports_hungarian_fluency_audit = True

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        if "Hungarian fluency classifier" in messages[0]["content"]:
            return _passing_fluency_audit(messages)
        return self.response


def test_hungarian_quality_flags_generic_foreign_and_unicode_corruption():
    answer = (
        "A mesters\u00e9ges intelligencia t\u00f6bb m\u00f3dszert haszn\u00e1l. "
        "A sz\u00f6veg loosely inspired p\u00e9ld\u00e1t ad, majd \ufffd hib\u00e1s karaktert tartalmaz."
    )

    issues = hungarian_output_quality_issues(answer)

    assert "foreign_language_fragment" in issues
    assert "corrupted_unicode" in issues

    validation = validate_response(
        "Válaszolj magyarul.",
        answer,
        constraints=build_task_constraints("Válaszolj magyarul."),
    )
    assert "corrupted_unicode" in validation.issues
    assert any("\ufffd" in snippet for snippet in validation.evidence)


def test_internal_repair_payload_marker_is_rejected_before_display():
    prompt = "Válaszolj magyarul."
    draft = (
        "A modellváltás során a memória állapota megmarad, "
        '"left_context": "belső javítási payload", majd a válasz folytatódik.'
    )

    validation = validate_response(
        prompt,
        draft,
        constraints=build_task_constraints(prompt),
    )

    assert validation.valid is False
    assert "internal_control_payload_leak" in validation.issues
    assert any("left_context" in snippet for snippet in validation.evidence)


def test_internal_repair_payload_marker_gets_bounded_repair():
    prompt = "Válaszolj magyarul."
    draft = (
        "A modellváltás során a memória állapota megmarad. "
        'A mondatba bekerült "left_context": "belső payload", ami nem felhasználói tartalom.'
    )

    class ProtocolLeakRepairClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                return _passing_fluency_audit(messages)
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            assert len(payload) == 1
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": "A mondatból eltávolítottuk a belső javítási payloadot.",
            }]})

    result = guard_response(
        ProtocolLeakRepairClient(),
        "gemma4:26b",
        prompt,
        draft,
        constraints=build_task_constraints(prompt),
    )

    assert "left_context" not in result
    assert "belső javítási payloadot" in result


def test_accented_hungarian_words_do_not_create_fake_english_function_words():
    answer = (
        "Minden fenti elem együttműködve biztosítja, hogy amikor egy webcímet "
        "beírok a böngészőbe, az oldal gyorsan és biztonságosan jelenjen meg a "
        "képernyőn, még akkor is, ha a szerver és a kliens egymástól távoli "
        "helyeken található."
    )

    assert "foreign_language_fragment" not in hungarian_output_quality_issues(answer)


def test_hungarian_quality_reports_only_bounded_foreign_fragment_evidence():
    evidence = hungarian_output_quality_evidence(
        "A rendszer called inference l\u00e9p\u00e9st hajtott v\u00e9gre."
    )

    assert evidence["foreign_language_fragment"] == ("called inference",)


def test_legitimate_technical_terms_are_not_treated_as_foreign_fragments():
    answer = (
        "Az LLM tokeneket dolgoz fel egy context window keretében. "
        "A training és inference GPU vagy Python eszközökkel is történhet."
    )

    assert "foreign_language_fragment" not in hungarian_output_quality_issues(answer)


def test_flagged_fluency_span_must_change_during_repair():
    prompt = "Válaszolj magyarul."
    bad = "hibas kifejezes"
    draft = "Ez a mondat " + bad + " szöveget tartalmaz."

    class Client:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segment = _audit_segments(messages)[0]
                return json.dumps({"judgments": [[
                    segment["id"], "semantic_language_corruption", [bad],
                ]]})
            return json.dumps({"repairs": [{"id": 0, "text": bad}]})

    with pytest.raises(LanguageRepairFailed, match="left flagged span unchanged"):
        guard_response(Client(), "gemma4:26b", prompt, draft)


@pytest.mark.parametrize("term", [
    "A g\u00e9pi tanul\u00e1s (machine learning) mint\u00e1kat elemez.",
    "A deep learning t\u00f6bb r\u00e9tegben dolgozhat.",
    "Az embedding vektoros reprezent\u00e1ci\u00f3t k\u00e9sz\u00edt.",
    "A Large Language Models (LLM) sz\u00f6veget dolgoznak fel.",
    "A context window, training, inference, tool use, GPU \u00e9s Python fontos fogalmak.",
])
def test_isolated_english_technical_terminology_is_not_a_foreign_fragment(term):
    assert "foreign_language_fragment" not in hungarian_output_quality_issues(term)


@pytest.mark.parametrize("answer", [
    "A sz\u00f6veg loosely inspired r\u00e9sszel folytat\u00f3dik.",
    "A folyamat called inference l\u00e9p\u00e9st is haszn\u00e1l.",
    "While black holes are difficult to study, this is an English sentence.",
])
def test_contextual_english_prose_is_still_flagged(answer):
    assert "foreign_language_fragment" in hungarian_output_quality_issues(answer)


def test_fluency_audit_accepts_schema_bound_status_and_findings_contract():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    draft = "Ez egy jó mondat. Ez a mondat működéskére hibát tartalmaz."

    class SchemaAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.audit_format = None

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                self.audit_format = kwargs.get("response_format")
                return json.dumps({
                    "status": ["pass", "malformed_morphology"],
                    "findings": [{
                        "id": 1,
                        "reason": "malformed_morphology",
                        "spans": ["működéskére"],
                    }],
                })
            return json.dumps({
                "repairs": [{"id": 0, "text": "működésre"}],
            })

    client = SchemaAuditClient()
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
    )

    assert result == draft.replace("működéskére", "működésre")
    assert isinstance(client.audit_format, dict)
    status_schema = client.audit_format["properties"]["status"]
    assert status_schema["minItems"] == 2
    assert status_schema["maxItems"] == 2


def test_fluency_audit_reconciles_pass_status_with_reasoned_exact_finding():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    draft = "Ez egy jó mondat. A rendszer szozaver újraindítása után is működik."

    class ContradictoryAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.calls = 0

        def chat_once(self, model, messages, **kwargs):
            self.calls += 1
            if "Hungarian fluency classifier" in messages[0]["content"]:
                return json.dumps({
                    "status": ["pass", "pass"],
                    "findings": [{
                        "id": 1,
                        "reason": "hybrid_or_pseudoword",
                        "spans": ["szozaver"],
                    }],
                })
            return json.dumps({
                "repairs": [{"id": 0, "text": "szoftver"}],
            })

    client = ContradictoryAuditClient()
    trace = RequestTrace("desktop")
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        trace=trace,
    )

    assert result == draft.replace("szozaver", "szoftver")
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "repair_required"
    assert snapshot["metadata"]["fluency_sentences_failed"] == 1
    assert snapshot["metadata"]["fluency_sentences_unresolved"] == 0
    assert snapshot["metadata"]["fluency_reason_codes"] == "hybrid_or_pseudoword"


def test_fluency_audit_pass_status_with_unreasoned_finding_is_partial_not_fatal():
    prompt = "Válaszolj magyarul."
    draft = "Ez egy jó mondat. Ez a mondat lehet hibás."

    class LegacyContradictoryAuditClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            return json.dumps({
                "status": ["pass", "pass"],
                "findings": [{"id": 1, "spans": ["lehet hibás"]}],
            })

    trace = RequestTrace("desktop")
    result = guard_response(
        LegacyContradictoryAuditClient(),
        "gemma4:26b",
        prompt,
        draft,
        trace=trace,
    )

    assert result == draft
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "partial"
    assert snapshot["metadata"]["fluency_sentences_unresolved"] == 1


def test_fluency_audit_missing_bounded_evidence_is_partial_not_request_fatal():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    draft = "Ez egy jó mondat. Ez a mondat nyelvileg lehet hibás."

    class MissingEvidenceAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.calls = 0

        def chat_once(self, model, messages, **kwargs):
            self.calls += 1
            return json.dumps({
                "status": ["pass", "malformed_morphology"],
                "findings": [],
            })

    client = MissingEvidenceAuditClient()
    trace = RequestTrace("desktop")
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        trace=trace,
    )

    assert result == draft
    assert client.calls == 1
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "partial"
    assert snapshot["metadata"]["fluency_sentences_audited"] == 2
    assert snapshot["metadata"]["fluency_sentences_failed"] == 1
    assert snapshot["metadata"]["fluency_sentences_unresolved"] == 1


def test_fluency_audit_backend_failure_degrades_without_discarding_clean_answer():
    prompt = "Válaszolj magyarul."
    draft = "Ez egy teljesen érthető magyar mondat."
    trace = RequestTrace("desktop")

    class BackendFailureClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                raise RuntimeError("400 Client Error: Bad Request")
            raise AssertionError("unexpected repair call")

    result = guard_response(
        BackendFailureClient(),
        "eurollm:9b-q4",
        prompt,
        draft,
        constraints=build_task_constraints(prompt),
        trace=trace,
    )

    assert result == draft
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "degraded"
    assert "400 Client Error" in snapshot["metadata"]["fluency_audit_failure_reason"]


def test_fluency_audit_contract_failure_degrades_without_discarding_clean_answer():
    prompt = "Válaszolj magyarul."
    draft = "Ez egy teljes, használható magyar válasz."

    class BrokenAuditClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            return "{not valid json"

    trace = RequestTrace("desktop")
    result = guard_response(
        BrokenAuditClient(),
        "gemma4:26b",
        prompt,
        draft,
        trace=trace,
    )

    assert result == draft
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "degraded"
    assert "valid JSON" in snapshot["metadata"]["fluency_audit_failure_reason"]


@pytest.mark.parametrize("suspicious, replacement, reason", [
    ("működéskére", "működésre", "malformed_morphology"),
    ("adatfolyamzáshoz", "adatfolyamhoz", "hybrid_or_pseudoword"),
    ("leglegfontosabb", "legfontosabb", "duplicated_morphology"),
    ("segítve nekik, hogy", "segít nekik abban, hogy", "broken_phrase"),
])
def test_fluency_audit_repairs_only_the_exact_suspicious_span(
    suspicious,
    replacement,
    reason,
):
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    draft = (
        "Az első bekezdés változatlan marad. "
        f"A második mondat {suspicious} hibát tartalmaz. "
        "A harmadik bekezdés változatlan marad."
    )

    class FluencyAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.audit_messages = None
            self.repair_messages = None

        def chat_once(self, model, messages, **kwargs):
            system = messages[0]["content"]
            if "Hungarian fluency classifier" in system:
                self.audit_messages = messages
                segments = _audit_segments(messages)
                return json.dumps({
                    "judgments": [
                        (
                            [item["id"], reason, [suspicious]]
                            if suspicious in item["text"]
                            else [item["id"], "pass"]
                        )
                        for item in segments
                    ],
                })
            self.repair_messages = messages
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            assert [item["text"] for item in payload] == [suspicious]
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": replacement,
            }]})

    client = FluencyAuditClient()
    trace = RequestTrace("desktop")
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        trace=trace,
    )

    assert result == draft.replace(suspicious, replacement)
    assert "Hungarian fluency classifier" in client.audit_messages[0]["content"]
    assert client.repair_messages is not None
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "repair_required"
    assert json.loads(snapshot["metadata"]["fluency_audit_evidence"]) == [suspicious]
    assert snapshot["metadata"]["fluency_sentences_audited"] == 3
    assert snapshot["metadata"]["fluency_sentences_failed"] == 1
    assert snapshot["metadata"]["fluency_reason_codes"] == reason
    assert snapshot["metadata"]["language_repair_span_count"] == 1
    assert "hungarian_fluency_audit" in snapshot["phases_ms"]


@pytest.mark.parametrize("term", [
    "machine learning",
    "deep learning",
    "embedding",
    "Large Language Models",
    "context window",
    "training",
    "inference",
    "tool use",
    "GPU",
    "Python",
])
def test_fluency_audit_discards_a_false_positive_technical_span(term):
    prompt = "Válaszolj magyarul."
    draft = f"A válasz a {term} fogalmát helyesen használja."

    class FalsePositiveAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.calls = 0

        def chat_once(self, model, messages, **kwargs):
            self.calls += 1
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segments = _audit_segments(messages)
                return json.dumps({
                    "judgments": [
                        (
                            [item["id"], "hybrid_or_pseudoword", [term]]
                            if term in item["text"]
                            else [item["id"], "pass"]
                        )
                        for item in segments
                    ],
                })
            raise AssertionError("a protected technical span must not be repaired")

    client = FalsePositiveAuditClient()
    trace = RequestTrace("desktop")

    assert guard_response(client, "gemma4:26b", prompt, draft, trace=trace) == draft
    assert client.calls == 1
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "pass"
    assert json.loads(snapshot["metadata"]["fluency_audit_evidence"]) == []
    assert snapshot["metadata"]["fluency_sentences_audited"] == 1
    assert snapshot["metadata"]["fluency_sentences_failed"] == 0


def test_cyrillic_hybrid_span_repairs_without_whole_response_false_positive():
    prompt = "Válaszolj magyarul."
    draft = (
        "A LocalAI Desktop Window Memory és Global Memory rétegei együtt működnek. "
        "A retrieval folyamat течениеben a rendszer megőrzi a releváns kontextust. "
        "A Remember ikon és a Python integráció változatlan marad."
    )

    class CyrillicHybridClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segments = _audit_segments(messages)
                return json.dumps({
                    "judgments": [
                        (
                            [item["id"], "semantic_language_corruption", ["течениеben"]]
                            if "течениеben" in item["text"]
                            else [item["id"], "pass"]
                        )
                        for item in segments
                    ],
                })
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            assert [item["text"] for item in payload] == ["течениеben"]
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": "során",
            }]})

    trace = RequestTrace("desktop")
    result = guard_response(
        CyrillicHybridClient(),
        "gemma4:26b",
        prompt,
        draft,
        trace=trace,
    )

    assert result == draft.replace("течениеben", "során")
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["repair_integrity_result"] == "pass"
    assert snapshot["metadata"]["language_repair_span_count"] == 1


def test_short_span_repair_cannot_expand_into_surrounding_sentence():
    prompt = "Válaszolj magyarul."
    draft = "A rendszer hibásalak használatával működik."

    class OverexpandedRepairClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segment = _audit_segments(messages)[0]
                return json.dumps({"judgments": [[
                    segment["id"],
                    "hybrid_or_pseudoword",
                    ["hibásalak"],
                ]]})
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": "Ez egy teljes, hosszú magyarázó mondat, amely nem bounded span javítás.",
            }]})

    with pytest.raises(RepairIntegrityFailed, match="span length limits"):
        guard_response(
            OverexpandedRepairClient(),
            "gemma4:26b",
            prompt,
            draft,
        )


def test_nonexact_fluency_span_is_partial_without_discarding_other_exact_repairs():
    prompt = "Válaszolj magyarul."
    draft = (
        "Az első mondat hibásalak miatt problémás. "
        "A második mondat rosszszó miatt hibás."
    )

    class MixedAuditClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segments = _audit_segments(messages)
                return json.dumps({"judgments": [
                    [
                        segments[0]["id"],
                        "hybrid_or_pseudoword",
                        ["hibas alak"],
                    ],
                    [
                        segments[1]["id"],
                        "hybrid_or_pseudoword",
                        ["rosszszó"],
                    ],
                ]})
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            assert [item["text"] for item in payload] == ["rosszszó"]
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": "hibás szó",
            }]})

    trace = RequestTrace("desktop")
    result = guard_response(
        MixedAuditClient(),
        "gemma4:26b",
        prompt,
        draft,
        trace=trace,
    )

    assert "hibásalak" in result
    assert "rosszszó" not in result
    assert "hibás szó" in result
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "partial"
    assert snapshot["metadata"]["fluency_sentences_failed"] == 2
    assert snapshot["metadata"]["fluency_sentences_unresolved"] == 1
    assert snapshot["metadata"]["language_repair_span_count"] == 1


def test_sentence_audit_covers_multiple_separated_hungarian_fluency_failures():
    prompt = "Válaszolj magyarul."
    repairs = {
        "tanulásképpen": ("tanulásként", "malformed_morphology"),
        "a modellek működik": ("a modellek működnek", "agreement_or_inflection"),
        "adatfolyamizálás": ("adatfeldolgozás", "hybrid_or_pseudoword"),
        "leglegjobb": ("legjobb", "duplicated_morphology"),
        "képes egyszerre emlékezni": (
            "egyszerre képes tárolni", "semantic_language_corruption",
        ),
        "a adatvédelem": ("az adatvédelem", "agreement_or_inflection"),
    }
    paragraphs = [
        "A tanulásképpen megfogalmazott lépés hibás.",
        "Ebben a mondatban a modellek működik rossz egyeztetéssel.",
        "Az adatfolyamizálás szó itt mesterségesen képzett alak.",
        "Ez a leglegjobb példának szánt mondat.",
        "A rendszer képes egyszerre emlékezni állítás helytelenül hangzik.",
        "Itt a adatvédelem előtt hibás a névelő.",
        "A machine learning fogalma ebben a mondatban helyes.",
        "A GPU teljesítménye önmagában nem dönt minden feladatról.",
        "A Python eszközök segíthetik a fejlesztést.",
        "A záró bekezdés nyelvileg rendben van.",
    ]
    draft = "\n\n".join(paragraphs)

    class MultiSentenceAuditClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.audit_segments = None
            self.repair_payload = None

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                self.audit_segments = _audit_segments(messages)
                judgments = []
                for item in self.audit_segments:
                    match = next(
                        (
                            (span, replacement, reason)
                            for span, (replacement, reason) in repairs.items()
                            if span in item["text"]
                        ),
                        None,
                    )
                    judgments.append(
                        [item["id"], "pass"]
                        if match is None
                        else [item["id"], match[2], [match[0]]]
                    )
                return json.dumps({"judgments": judgments})
            self.repair_payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({"repairs": [
                {
                    "id": item["id"],
                    "text": repairs[item["text"]][0],
                }
                for item in self.repair_payload
            ]})

    client = MultiSentenceAuditClient()
    trace = RequestTrace("desktop")
    result = guard_response(client, "gemma4:26b", prompt, draft, trace=trace)

    expected = draft
    for original, (replacement, _) in repairs.items():
        expected = expected.replace(original, replacement)
    assert result == expected
    assert [item["id"] for item in client.audit_segments] == list(range(10))
    assert [item["text"] for item in client.repair_payload] == list(repairs)
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["fluency_sentences_audited"] == 10
    assert snapshot["metadata"]["fluency_sentences_failed"] == len(repairs)
    assert snapshot["metadata"]["fluency_reason_codes"] == (
        "malformed_morphology,agreement_or_inflection,hybrid_or_pseudoword,"
        "duplicated_morphology,semantic_language_corruption"
    )
    assert snapshot["metadata"]["language_repair_span_count"] == len(repairs)


def test_sentence_audit_combines_overlapping_exact_spans_before_repair():
    prompt = "Válaszolj magyarul."
    draft = "Ebben a mondatban a adatvédelem fontos szerepet kap."

    class OverlappingSpanClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            if "Hungarian fluency classifier" in messages[0]["content"]:
                segment = _audit_segments(messages)[0]
                return json.dumps({"judgments": [[
                    segment["id"],
                    "agreement_or_inflection",
                    ["a adatvédelem", "adatvédelem fontos"],
                ]]})
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            assert len(payload) == 1
            assert payload[0]["text"] == "a adatvédelem fontos"
            return json.dumps({"repairs": [{
                "id": payload[0]["id"],
                "text": "az adatvédelem fontos",
            }]})

    trace = RequestTrace("desktop")
    assert guard_response(
        OverlappingSpanClient(), "gemma4:26b", prompt, draft, trace=trace,
    ) == "Ebben a mondatban az adatvédelem fontos szerepet kap."
    assert trace.snapshot()["metadata"]["language_repair_span_count"] == 1


def test_sentence_audit_omission_degrades_without_discarding_complete_answer():
    prompt = "Válaszolj magyarul."
    draft = "Az első mondat rendben van. A második is rendben van."

    class IncompleteAuditClient:
        supports_hungarian_fluency_audit = True

        def chat_once(self, model, messages, **kwargs):
            assert len(_audit_segments(messages)) == 2
            return json.dumps({"judgments": [[0, "pass"]]})

    trace = RequestTrace("desktop")
    result = guard_response(
        IncompleteAuditClient(),
        "gemma4:26b",
        prompt,
        draft,
        trace=trace,
    )

    assert result == draft
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "degraded"
    assert "must judge every response sentence" in snapshot["metadata"]["fluency_audit_failure_reason"]


def test_clean_long_hungarian_answer_passes_without_editorial_repair():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    constraints = build_task_constraints(prompt)
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    draft = "\n\n".join(paragraphs)
    client = EditorialRepairClient("this must not be used")

    validation = validate_response(prompt, draft, constraints=constraints)
    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
    )

    assert validation.valid is True
    assert result == draft
    assert len(client.calls) == 1
    assert "Hungarian fluency classifier" in client.calls[0][1][0]["content"]


def test_clean_long_hungarian_ai_answer_with_technical_terms_needs_no_repair():
    prompt = "\u00cdrj r\u00e9szletes magyar \u00f6sszefoglal\u00f3t a mesters\u00e9ges intelligenci\u00e1r\u00f3l."
    constraints = build_task_constraints(prompt)
    paragraph = (
        "A g\u00e9pi tanul\u00e1s (machine learning), a deep learning \u00e9s az embedding "
        "seg\u00edt a mint\u00e1k feldolgoz\u00e1s\u00e1ban. A Large Language Models (LLM) "
        "a context window, training, inference, tool use, GPU \u00e9s Python eszk\u00f6zeit "
        "is haszn\u00e1lhatja. "
    )
    draft = "\n\n".join(paragraph * 4 for _ in range(10))
    client = EditorialRepairClient("this must not be used")
    trace = RequestTrace("desktop")

    assert guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
        trace=trace,
    ) == draft
    assert len(client.calls) == 1
    assert "Hungarian fluency classifier" in client.calls[0][1][0]["content"]
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["fluency_sentences_failed"] == 0
    assert snapshot["metadata"].get("language_repair_span_count", 0) == 0


def test_desktop_clean_long_answer_uses_primary_generation_and_audit_without_repair():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    answer = "\n\n".join(paragraphs)
    client = SingleGenerationClient(answer)
    trace = RequestTrace("desktop")
    worker = AdaptiveChatWorker(
        client,
        "gemma4:26b",
        [{"role": "user", "content": prompt}],
        prompt,
        constraints=build_task_constraints(prompt),
        trace=trace,
        output_budget=2048,
    )
    tokens = []
    errors = []
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)

    worker.run()

    snapshot = trace.snapshot()
    assert errors == []
    assert "".join(tokens) == answer.strip()
    assert len(client.calls) == 2
    assert snapshot["phases_ms"].get("primary_generation") is not None
    assert snapshot["phases_ms"].get("language_validation") is not None
    assert "language_repair" not in snapshot["phases_ms"]
    assert snapshot["metadata"]["language_validation_result"] == "pass"
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "pass"


def test_contaminated_long_hungarian_answer_gets_one_bounded_editorial_repair():
    prompt = "Írj részletes magyar összefoglalót a mesterséges intelligenciáról."
    constraints = build_task_constraints(prompt)
    paragraphs = [
        (
            f"{index}. bekezdés: A mesterséges intelligencia adatmintákból tanul, "
            "és az eredményt a feladat céljához igazítja. "
        ) * 4
        for index in range(1, 5)
    ]
    draft = "\n\n".join(paragraphs).replace(
        "adatmintákból", "loosely inspired adatminta alapján", 1
    )
    class SpanRepairClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages, **kwargs):
            self.calls.append((model, messages, kwargs))
            if "Hungarian fluency classifier" in messages[0]["content"]:
                return _passing_fluency_audit(messages)
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({
                "repairs": [{
                    "id": item["id"],
                    "text": item["text"].replace(
                        "loosely inspired adatminta alapján", "adatmintákból"
                    ),
                } for item in payload],
            })

    repaired = draft.replace("loosely inspired adatminta alapján", "adatmintákból")
    client = SpanRepairClient()
    trace = RequestTrace("desktop")

    result = guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
        trace=trace,
    )

    assert result == repaired
    assert len(client.calls) == 2
    assert repair_preserves_response_shape(draft, result)
    payload = json.loads(client.calls[1][1][1]["content"].split(
        "BOUNDED SPANS TO REPAIR:\n", 1
    )[1])
    assert len(payload) == 1
    assert "loosely inspired" in payload[0]["text"]
    snapshot = trace.snapshot()
    assert json.loads(snapshot["metadata"]["language_validation_evidence"]) == [
        "loosely inspired",
    ]
    assert snapshot["metadata"]["language_repair_span_count"] == 1
    assert snapshot["metadata"]["language_repair_result"] == "completed"
    assert snapshot["metadata"]["repair_integrity_result"] == "pass"
    assert {"language_validation", "language_repair", "repair_integrity_validation"} <= set(
        snapshot["phases_ms"]
    )


def test_multiple_separated_contaminated_spans_preserve_untouched_text():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    untouched = "A harmadik bekezdés változatlan marad, benne az LLM és a GPU kifejezésekkel."
    draft = (
        "Az OpenAI modell ára 42 EUR, forrás: https://example.test. 잘못 mondat.\n\n"
        "A második bekezdés loosely inspired kevert nyelvű maradt.\n\n"
        + untouched
    )

    class BatchSpanClient:
        supports_hungarian_fluency_audit = True

        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages, **kwargs):
            self.calls.append((model, messages, kwargs))
            if "Hungarian fluency classifier" in messages[0]["content"]:
                return _passing_fluency_audit(messages)
            payload = json.loads(messages[1]["content"].split(
                "BOUNDED SPANS TO REPAIR:\n", 1
            )[1])
            return json.dumps({"repairs": [
                {
                    "id": item["id"],
                    "text": item["text"]
                    .replace("잘못", "hibás")
                    .replace("loosely inspired", "véletlenül"),
                }
                for item in payload
            ]})

    client = BatchSpanClient()
    result = guard_response(
        client, "gemma4:26b", prompt, draft, constraints=constraints,
    )

    assert len(client.calls) == 2
    payload = json.loads(client.calls[1][1][1]["content"].split(
        "BOUNDED SPANS TO REPAIR:\n", 1
    )[1])
    assert len(payload) == 2
    assert untouched in result
    assert "OpenAI" in result
    assert "42 EUR" in result
    assert "https://example.test" in result
    assert "LLM" in result and "GPU" in result


def test_bounded_repair_that_keeps_contamination_is_language_repair_failure():
    prompt = "Válaszolj magyarul."
    constraints = build_task_constraints(prompt)
    client = EditorialRepairClient("Ez a mondat továbbra is loosely inspired szöveget tartalmaz.")
    trace = RequestTrace("desktop")

    with pytest.raises(LanguageRepairFailed, match="language_repair_failed") as exc:
        guard_response(
            client,
            "gemma4:26b",
            prompt,
            "Ez a mondat loosely inspired szöveget tartalmaz.",
            constraints=constraints,
            trace=trace,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_classification"] == "language_repair_failed"
    assert metadata["ollama_call_phase"] == "repair_integrity_validation"
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["language_repair_result"] == "completed"
    assert snapshot["metadata"]["repair_integrity_result"] == "failed"
    assert json.loads(snapshot["metadata"]["repair_integrity_evidence"]) == [
        "loosely inspired",
    ]


def test_discord_and_desktop_use_the_shared_span_repair_guard():
    from app.discord_bot_bridge import DiscordBotBridge

    desktop_source = inspect.getsource(AdaptiveChatWorker.run)
    discord_source = inspect.getsource(DiscordBotBridge._answer_prompt)

    assert "guard_response(" in desktop_source
    assert "guard_response(" in discord_source


def test_editorial_repair_rejects_shortened_long_answer():
    original = "\n\n".join(["Ez egy hosszú magyar bekezdés. " * 30] * 4)
    shortened = "Ez rövid lett."

    assert repair_preserves_response_shape(original, shortened) is False
