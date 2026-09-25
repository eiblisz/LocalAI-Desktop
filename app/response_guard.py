import json
import re
from dataclasses import dataclass

from .language_policy import (
    effective_response_language,
    hungarian_output_quality_issues,
    repair_preserves_factual_literals,
    repair_preserves_response_shape,
    response_language_matches,
    response_validation_text,
)
from .task_constraints import TaskConstraints


class ResponseValidationError(RuntimeError):
    pass


class LanguageRepairFailed(ResponseValidationError):
    """A bounded linguistic repair left invalid prose behind."""


class RepairIntegrityFailed(ResponseValidationError):
    """A repair attempted to alter protected response content."""


def _tag_repair_failure(exc, *, stage, classification):
    """Make a validation failure visible without calling it an Ollama failure."""
    exc.localai_failure_stage = str(stage)
    exc.localai_failure_classification = str(classification)
    exc.localai_ollama_call_phase = str(stage)
    return exc


@dataclass(frozen=True)
class ResponseValidation:
    valid: bool
    expected_language: str
    issues: tuple[str, ...] = ()


_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_SENTENCE_BREAK_RE = re.compile(r"[.!?]+(?=\s|$)|\n{2,}")
_MAX_REPAIR_SPANS = 6
_MAX_REPAIR_SPAN_CHARS = 900

_EXPLICIT_SCRIPT_REQUEST_MARKERS = (
    "korean",
    "koreai",
    "한국어",
    "hangul",
    "japanese",
    "japán",
    "japan",
    "日本語",
    "chinese",
    "kínai",
    "kinai",
    "中文",
)


def _expected_language(user_text, constraints=None):
    if isinstance(constraints, TaskConstraints):
        language = str(constraints.response_language or "").strip().lower()
        if language in {"hu", "de", "en"}:
            return language
    return effective_response_language(user_text)


def _script_change_explicitly_requested(user_text):
    folded = str(user_text or "").casefold()
    return any(marker.casefold() in folded for marker in _EXPLICIT_SCRIPT_REQUEST_MARKERS)


def unexpected_script_issues(user_text, response_text, constraints=None):
    expected = _expected_language(user_text, constraints)
    if expected not in {"hu", "de", "en"}:
        return ()
    if _script_change_explicitly_requested(user_text):
        return ()

    text = response_validation_text(response_text)
    issues = []
    if _HANGUL_RE.search(text):
        issues.append("unexpected_hangul")
    if _CJK_RE.search(text):
        issues.append("unexpected_cjk")
    return tuple(issues)


def validate_response(
    user_text,
    response_text,
    constraints=None,
):
    expected = _expected_language(user_text, constraints)
    issues = list(unexpected_script_issues(user_text, response_text, constraints))

    if expected in {"hu", "de", "en"} and not response_language_matches(
        user_text,
        response_text,
    ):
        issues.append("language_mismatch")
    if expected == "hu":
        issues.extend(
            hungarian_output_quality_issues(response_text)
        )

    return ResponseValidation(
        valid=not issues,
        expected_language=expected,
        issues=tuple(dict.fromkeys(issues)),
    )


def _repair_messages(user_text, spans, constraints=None):
    parent_intent = ""
    if isinstance(constraints, TaskConstraints):
        parent_intent = str(constraints.parent_intent or "").strip()

    expected = _expected_language(user_text, constraints)
    language_name = {
        "hu": "Hungarian",
        "de": "German",
        "en": "English",
    }.get(expected, "requested-language")
    system = (
        f"Edit only the supplied contaminated {language_name} text spans. Do not rewrite or summarize "
        "the surrounding answer. Remove accidental foreign-language/script leakage, corrupted "
        "Unicode and malformed hybrid words while preserving the meaning. Preserve every number, "
        "URL, date, currency value, product/model name, proper name, technical term and factual "
        "claim exactly. Legitimate English technical terms include LLM, token, context window, "
        "training, inference, tool use, GPU and Python. Return strict JSON only in this shape: "
        '{"repairs":[{"id":0,"text":"repaired span"}]}. Return every id exactly once and no other text.'
    )
    if parent_intent:
        system += (
            " The repaired answer must remain inside the parent task scope: "
            + parent_intent[:1800]
        )

    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                "CURRENT USER REQUEST:\n"
                + str(user_text or "")
                + "\n\nBOUNDED SPANS TO REPAIR:\n"
                + json.dumps(spans, ensure_ascii=False)
            ),
        },
    ]


def _sentence_spans(text):
    """Split prose into bounded editable spans while retaining delimiters."""
    raw = str(text or "")
    start = 0
    spans = []
    for match in _SENTENCE_BREAK_RE.finditer(raw):
        end = match.end()
        if raw[start:end].strip():
            spans.append((start, end))
        start = end
    if raw[start:].strip():
        spans.append((start, len(raw)))
    return spans


def _repair_spans(user_text, response_text, constraints=None):
    raw = str(response_text or "")
    repairs = []
    for index, (start, end) in enumerate(_sentence_spans(raw)):
        original = raw[start:end]
        leading = original[:len(original) - len(original.lstrip())]
        body = original.strip()
        if not body:
            continue
        validation = validate_response(user_text, body, constraints=constraints)
        if validation.valid:
            continue
        if len(body) > _MAX_REPAIR_SPAN_CHARS:
            raise LanguageRepairFailed(
                "language_repair_failed: contaminated span exceeds bounded repair limit"
            )
        repairs.append({
            "id": index,
            "start": start,
            "end": end,
            "text": body,
            "prefix": leading,
            "suffix": original[len(leading) + len(body):],
            "left_context": raw[max(0, start - 240):start],
            "right_context": raw[end:min(len(raw), end + 240)],
        })

    if not repairs:
        raise LanguageRepairFailed(
            "language_repair_failed: no bounded contaminated span was identified"
        )
    if len(repairs) > _MAX_REPAIR_SPANS:
        raise LanguageRepairFailed(
            "language_repair_failed: too many contaminated spans for one bounded repair"
        )
    return repairs


def _parse_span_repairs(raw_response, spans):
    raw = str(raw_response or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    expected_ids = {item["id"] for item in spans}
    if len(spans) == 1 and raw and not raw.startswith("{"):
        return {spans[0]["id"]: raw}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LanguageRepairFailed(
            "language_repair_failed: bounded repair did not return valid JSON"
        ) from exc
    items = payload.get("repairs") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise LanguageRepairFailed(
            "language_repair_failed: bounded repair returned no repair list"
        )
    parsed = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id")
        text = item.get("text")
        if isinstance(identifier, int) and isinstance(text, str):
            parsed[identifier] = text.strip()
    if set(parsed) != expected_ids:
        raise LanguageRepairFailed(
            "language_repair_failed: bounded repair returned incomplete span ids"
        )
    return parsed


def _splice_span_repairs(original, spans, replacements, *, user_text):
    pieces = []
    cursor = 0
    for span in spans:
        start = span["start"]
        end = span["end"]
        replacement = str(replacements[span["id"]] or "").strip()
        if not replacement:
            raise LanguageRepairFailed(
                "language_repair_failed: bounded repair returned an empty span"
            )
        original_length = len(span["text"])
        if original_length >= 40 and not (
            original_length * 0.4 <= len(replacement) <= original_length * 3.0
        ):
            raise RepairIntegrityFailed(
                "repair_integrity_failed: bounded repair exceeded span length limits"
            )
        if not repair_preserves_response_shape(
            span["text"],
            replacement,
            preserve_proper_names=response_language_matches(user_text, span["text"]),
        ):
            raise RepairIntegrityFailed(
                "repair_integrity_failed: bounded repair changed protected span content"
            )
        pieces.extend((
            str(original)[cursor:start],
            span["prefix"],
            replacement,
            span["suffix"],
        ))
        cursor = end
    pieces.append(str(original)[cursor:])
    return "".join(pieces)


def guard_response(
    client,
    model,
    user_text,
    response_text,
    *,
    constraints=None,
    control=None,
    output_budget=None,
    trace=None,
    phase_callback=None,
):
    """
    Validate one final model response and perform at most one bounded repair.

    The invalid original draft is never returned to the caller.
    """
    draft = str(response_text or "")
    if not draft.strip():
        return draft

    if trace is not None:
        trace.begin("language_validation")
    validation = validate_response(user_text, draft, constraints=constraints)
    if trace is not None:
        trace.end(
            "language_validation",
            language_validation_result=("pass" if validation.valid else "repair_required"),
            language_validation_issues=",".join(validation.issues),
        )
    if validation.valid:
        return draft

    try:
        spans = _repair_spans(user_text, draft, constraints=constraints)
    except LanguageRepairFailed as exc:
        raise _tag_repair_failure(
            exc,
            stage="language_validation",
            classification="language_repair_failed",
        )
    repair_payload = [
        {
            "id": item["id"],
            "text": item["text"],
            "left_context": item["left_context"],
            "right_context": item["right_context"],
        }
        for item in spans
    ]
    repair_messages = _repair_messages(
        user_text,
        repair_payload,
        constraints=constraints,
    )
    if control is not None:
        control.claim_repair()
    call_kwargs = {"model": model, "messages": repair_messages}
    if control is not None:
        call_kwargs["control"] = control
    if output_budget is not None:
        call_kwargs["num_predict"] = min(768, max(64, int(output_budget)))
    call_kwargs["call_phase"] = "language_repair"
    call_kwargs["response_format"] = "json"
    if trace is not None:
        trace.begin("language_repair")
        trace.add_metadata(
            language_repair_attempted=True,
            language_repair_span_count=len(spans),
            language_repair_span_chars=sum(len(item["text"]) for item in spans),
        )
    if callable(phase_callback):
        phase_callback("Nyelvi javítás")
    try:
        while True:
            try:
                repair_result = client.chat_once(**call_kwargs).strip()
                break
            except TypeError as exc:
                # Lightweight test and extension clients may implement the older
                # client signature. The real Ollama client receives the shared budget.
                if "control" in str(exc) and "control" in call_kwargs:
                    call_kwargs.pop("control")
                    continue
                if "num_predict" in str(exc) and "num_predict" in call_kwargs:
                    call_kwargs.pop("num_predict")
                    continue
                if "call_phase" in str(exc) and "call_phase" in call_kwargs:
                    call_kwargs.pop("call_phase")
                    continue
                if "response_format" in str(exc) and "response_format" in call_kwargs:
                    call_kwargs.pop("response_format")
                    continue
                raise
    except Exception:
        if trace is not None:
            trace.end("language_repair", language_repair_result="failed")
        raise
    else:
        if trace is not None:
            trace.end("language_repair", language_repair_result="completed")

    if trace is not None:
        trace.begin("repair_integrity_validation")
    try:
        replacements = _parse_span_repairs(repair_result, spans)
        repaired = _splice_span_repairs(
            draft,
            spans,
            replacements,
            user_text=user_text,
        )
    except RepairIntegrityFailed as exc:
        if trace is not None:
            trace.end(
                "repair_integrity_validation",
                repair_integrity_result="failed",
                repair_integrity_issues="repair_integrity_failed",
            )
        raise _tag_repair_failure(
            exc,
            stage="repair_integrity_validation",
            classification="integrity_failed",
        )
    except LanguageRepairFailed as exc:
        if trace is not None:
            trace.end(
                "repair_integrity_validation",
                repair_integrity_result="failed",
                repair_integrity_issues="language_repair_failed",
            )
        raise _tag_repair_failure(
            exc,
            stage="language_repair",
            classification="language_repair_failed",
        )

    repaired_validation = validate_response(user_text, repaired, constraints=constraints)
    integrity_issue = ""
    if not repair_preserves_factual_literals(draft, repaired):
        integrity_issue = "factual_literal_changed"
    elif not repair_preserves_response_shape(
        draft,
        repaired,
        preserve_proper_names=response_language_matches(user_text, draft),
    ):
        integrity_issue = "response_shape_or_literal_changed"
    if integrity_issue:
        repaired_validation = ResponseValidation(
            valid=False,
            expected_language=repaired_validation.expected_language,
            issues=tuple(dict.fromkeys(
                repaired_validation.issues + (integrity_issue,)
            )),
        )
    if trace is not None:
        trace.end(
            "repair_integrity_validation",
            repair_integrity_result=("pass" if repaired and repaired_validation.valid else "failed"),
            repair_integrity_issues=",".join(repaired_validation.issues),
        )
    if integrity_issue:
        raise _tag_repair_failure(
            RepairIntegrityFailed(
                "repair_integrity_failed: " + integrity_issue
            ),
            stage="repair_integrity_validation",
            classification="integrity_failed",
        )
    if repaired and repaired_validation.valid:
        return repaired

    raise _tag_repair_failure(
        LanguageRepairFailed(
            "language_repair_failed: bounded repair still contains invalid prose: "
            + ", ".join(repaired_validation.issues or validation.issues)
        ),
        stage="repair_integrity_validation",
        classification="language_repair_failed",
    )
