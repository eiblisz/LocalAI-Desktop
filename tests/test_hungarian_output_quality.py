import json
import inspect

import pytest

from app.language_policy import (
    hungarian_output_quality_evidence,
    hungarian_output_quality_issues,
    repair_preserves_response_shape,
)
from app.request_trace import RequestTrace
from app.response_guard import LanguageRepairFailed, guard_response, validate_response
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker
from app.ollama_client import ollama_failure_metadata


class EditorialRepairClient:
    supports_hungarian_fluency_audit = True

    def __init__(self, repaired):
        self.repaired = repaired
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        if "Hungarian fluency classifier" in messages[0]["content"]:
            return json.dumps({"status": "pass", "findings": []})
        return self.repaired


class SingleGenerationClient:
    supports_hungarian_fluency_audit = True

    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_once(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        if "Hungarian fluency classifier" in messages[0]["content"]:
            return json.dumps({"status": "pass", "findings": []})
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


@pytest.mark.parametrize("suspicious, replacement, reason", [
    ("működéskére", "működésre", "malformed_morphology"),
    ("adatfolyamzáshoz", "adatfolyamhoz", "hybrid_word"),
    ("leglegfontosabb", "legfontosabb", "duplicated_morphology"),
    ("segítve nekik, hogy", "segít nekik abban, hogy", "broken_local_phrase"),
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
                return json.dumps({
                    "status": "repair_required",
                    "findings": [{"span": suspicious, "reason": reason}],
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
                return json.dumps({
                    "status": "repair_required",
                    "findings": [{"span": term, "reason": "hybrid_word"}],
                })
            raise AssertionError("a protected technical span must not be repaired")

    client = FalsePositiveAuditClient()
    trace = RequestTrace("desktop")

    assert guard_response(client, "gemma4:26b", prompt, draft, trace=trace) == draft
    assert client.calls == 1
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["hungarian_fluency_audit_result"] == "pass"
    assert json.loads(snapshot["metadata"]["fluency_audit_evidence"]) == []


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

    assert guard_response(
        client,
        "gemma4:26b",
        prompt,
        draft,
        constraints=constraints,
        output_budget=2048,
    ) == draft
    assert len(client.calls) == 1
    assert "Hungarian fluency classifier" in client.calls[0][1][0]["content"]


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
                return json.dumps({"status": "pass", "findings": []})
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
                return json.dumps({"status": "pass", "findings": []})
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
