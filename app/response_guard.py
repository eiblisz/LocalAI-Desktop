import json
import re
from dataclasses import dataclass

from .language_policy import (
    effective_response_language,
    hungarian_output_quality_evidence,
    repair_preserves_factual_literals,
    repair_preserves_response_shape,
    protected_factual_literals,
    protected_response_literals,
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


class FluencyAuditFailed(ResponseValidationError):
    """The bounded Hungarian fluency classifier did not return safe findings."""


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
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class FluencyAuditResult:
    findings: tuple = ()
    sentences_audited: int = 0
    sentences_failed: int = 0
    sentences_unresolved: int = 0
    reason_codes: tuple[str, ...] = ()


_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_HANGUL_SPAN_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+")
_CJK_SPAN_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+"
)
_SENTENCE_BREAK_RE = re.compile(r"[.!?]+(?=\s|$)|\n{2,}")
_MAX_REPAIR_SPANS = 8
_MAX_REPAIR_SPAN_CHARS = 900
_MAX_FLUENCY_FINDINGS = 8
_MAX_FLUENCY_SPAN_CHARS = 280
_MAX_FLUENCY_SPANS_PER_SENTENCE = 3
_FLUENCY_REASON_CODES = frozenset({
    "malformed_morphology",
    "agreement_or_inflection",
    "broken_phrase",
    "hybrid_or_pseudoword",
    "duplicated_morphology",
    "semantic_language_corruption",
})
_AUDIT_PROTECTED_SPAN_RE = re.compile(
    r"https?://\S+|`[^`\n]+`|\"[^\"\n]+\"|„[^”\n]+”|“[^”\n]+”",
    flags=re.UNICODE,
)
_ASCII_TECHNICAL_SPAN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ._+/#:-]*$")
_DUPLICATED_PREFIX_RE = re.compile(r"^([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{2,5})\1", re.UNICODE)

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


def _bounded_response_evidence(value, limit=220):
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit - 3].rstrip() + "..."


def unexpected_script_evidence(user_text, response_text, constraints=None):
    expected = _expected_language(user_text, constraints)
    if expected not in {"hu", "de", "en"}:
        return {}
    if _script_change_explicitly_requested(user_text):
        return {}

    text = response_validation_text(response_text)
    evidence = {}
    hangul = tuple(
        _bounded_response_evidence(match.group(0))
        for match in _HANGUL_SPAN_RE.finditer(text)
    )[:_MAX_FLUENCY_FINDINGS]
    cjk = tuple(
        _bounded_response_evidence(match.group(0))
        for match in _CJK_SPAN_RE.finditer(text)
    )[:_MAX_FLUENCY_FINDINGS]
    if hangul:
        evidence["unexpected_hangul"] = tuple(dict.fromkeys(hangul))
    if cjk:
        evidence["unexpected_cjk"] = tuple(dict.fromkeys(cjk))
    return evidence


def unexpected_script_issues(user_text, response_text, constraints=None):
    return tuple(unexpected_script_evidence(user_text, response_text, constraints))


def validate_response(
    user_text,
    response_text,
    constraints=None,
):
    expected = _expected_language(user_text, constraints)
    script_evidence = unexpected_script_evidence(
        user_text,
        response_text,
        constraints,
    )
    issues = list(script_evidence)
    evidence = [
        snippet
        for snippets in script_evidence.values()
        for snippet in snippets
    ]

    if expected in {"hu", "de", "en"} and not response_language_matches(
        user_text,
        response_text,
    ):
        issues.append("language_mismatch")
    if expected == "hu":
        quality_evidence = hungarian_output_quality_evidence(response_text)
        issues.extend(quality_evidence)
        evidence.extend(
            snippet
            for snippets in quality_evidence.values()
            for snippet in snippets
        )

    return ResponseValidation(
        valid=not issues,
        expected_language=expected,
        issues=tuple(dict.fromkeys(issues)),
        evidence=tuple(dict.fromkeys(evidence)),
    )


def _validation_evidence_json(validation):
    return json.dumps(list(validation.evidence), ensure_ascii=False)


def _fluency_audit_segments(response_text):
    """Expose every user-visible sentence as a stable, exact audit unit."""
    raw = str(response_text or "")
    segments = []
    for start, end in _sentence_spans(raw):
        original = raw[start:end]
        leading = len(original) - len(original.lstrip())
        text = original.strip()
        if not text:
            continue
        text_start = start + leading
        segments.append({
            "id": len(segments),
            "start": text_start,
            "end": text_start + len(text),
            "text": text,
        })
    return tuple(segments)


def _fluency_audit_response_schema(segment_count):
    count = max(1, int(segment_count))
    statuses = ["pass"] + sorted(_FLUENCY_REASON_CODES)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "findings"],
        "properties": {
            "status": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {"type": "string", "enum": statuses},
            },
            "findings": {
                "type": "array",
                "maxItems": min(count, _MAX_FLUENCY_FINDINGS),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "reason", "spans"],
                    "properties": {
                        "id": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": count - 1,
                        },
                        "reason": {
                            "type": "string",
                            "enum": sorted(_FLUENCY_REASON_CODES),
                        },
                        "spans": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": _MAX_FLUENCY_SPANS_PER_SENTENCE,
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": _MAX_FLUENCY_SPAN_CHARS,
                            },
                        },
                    },
                },
            },
        },
    }


def _fluency_audit_messages(segments):
    return [
        {
            "role": "system",
            "content": (
                "You are a Hungarian fluency classifier, not a writer. Inspect every supplied "
                "user-visible response segment in order. Return strict JSON with two fields: "
                "status and findings. status MUST contain exactly one entry for every segment, "
                "in the same order. Each status is pass or one of: malformed_morphology, "
                "agreement_or_inflection, broken_phrase, hybrid_or_pseudoword, "
                "duplicated_morphology, semantic_language_corruption. findings contains entries "
                "only for non-pass segments, each as {id, reason, spans}, where id is the supplied "
                "stable segment id, reason MUST equal the non-pass status for that segment, and "
                "spans are one or more exact short substrings copied byte-for-byte from that same "
                "segment. Check every sentence for broken Hungarian inflection, "
                "agreement, article choice, verb complements, pseudo-words, duplicated morphology "
                "and locally nonsensical phrasing. A sentence that is mostly good can still fail "
                "for one short malformed span. Do not rewrite anything. Do not flag legitimate "
                "English technical terminology, proper names, URLs, numbers, code, or quoted "
                "source titles. If uncertain about a sentence, mark it pass."
            ),
        },
        {
            "role": "user",
            "content": (
                "USER-VISIBLE RESPONSE SEGMENTS TO AUDIT:\n"
                + json.dumps(
                    [{"id": item["id"], "text": item["text"]} for item in segments],
                    ensure_ascii=False,
                )
            ),
        },
    ]


def _chat_once_compat(client, call_kwargs):
    """Call shared clients while allowing existing lightweight extension clients."""
    while True:
        try:
            return client.chat_once(**call_kwargs).strip()
        except TypeError as exc:
            # Test and extension clients may implement an earlier chat_once signature.
            for name in ("control", "num_predict", "call_phase", "response_format"):
                if name in str(exc) and name in call_kwargs:
                    call_kwargs.pop(name)
                    break
            else:
                raise


def _fluency_span_is_protected(raw_response_text, start, end, span, reason):
    if any(
        protected.start() < end and start < protected.end()
        for protected in _AUDIT_PROTECTED_SPAN_RE.finditer(raw_response_text)
    ):
        return True
    if protected_factual_literals(span) or protected_response_literals(span):
        return True
    return bool(
        _ASCII_TECHNICAL_SPAN_RE.fullmatch(span)
        and not (
            reason == "duplicated_morphology" and _DUPLICATED_PREFIX_RE.match(span)
        )
    )


def _parse_fluency_audit(raw_response, response_text, segments):
    raw = str(raw_response or "").strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FluencyAuditFailed(
            "fluency_audit_failed: Hungarian fluency audit did not return valid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise FluencyAuditFailed(
            "fluency_audit_failed: Hungarian fluency audit returned no object"
        )

    # Backward-compatible parsing keeps lightweight extension/test clients
    # working while the real Ollama path uses the more compact, schema-bound
    # status/findings contract below.
    if "judgments" in payload:
        judgments = payload.get("judgments")
        if not isinstance(judgments, list) or len(judgments) != len(segments):
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency audit must judge every response sentence"
            )
        status_values = [None] * len(segments)
        findings_payload = []
        for item in judgments:
            if not isinstance(item, list) or len(item) not in {2, 3}:
                raise FluencyAuditFailed(
                    "fluency_audit_failed: Hungarian fluency audit judgment is malformed"
                )
            identifier = item[0]
            status = str(item[1] or "").strip().lower()
            if not isinstance(identifier, int) or not (0 <= identifier < len(segments)):
                raise FluencyAuditFailed(
                    "fluency_audit_failed: Hungarian fluency audit id is invalid"
                )
            if status_values[identifier] is not None:
                raise FluencyAuditFailed(
                    "fluency_audit_failed: Hungarian fluency audit ids are duplicated"
                )
            status_values[identifier] = status
            if status != "pass":
                if len(item) != 3 or not isinstance(item[2], list):
                    raise FluencyAuditFailed(
                        "fluency_audit_failed: Hungarian fluency failure judgment is invalid"
                    )
                findings_payload.append({"id": identifier, "spans": item[2]})
        if any(value is None for value in status_values):
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency audit omitted a response sentence"
            )
    else:
        status_values = payload.get("status")
        findings_payload = payload.get("findings")
        if (
            not isinstance(status_values, list)
            or len(status_values) != len(segments)
            or not isinstance(findings_payload, list)
        ):
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency audit coverage is incomplete"
            )
        status_values = [str(value or "").strip().lower() for value in status_values]

    for status in status_values:
        if status != "pass" and status not in _FLUENCY_REASON_CODES:
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency audit status is invalid"
            )

    segments_by_id = {item["id"]: item for item in segments}
    findings_by_id = {}
    for finding in findings_payload:
        if not isinstance(finding, dict):
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency finding is malformed"
            )
        identifier = finding.get("id")
        spans = finding.get("spans")
        finding_reason = str(finding.get("reason") or "").strip().lower()
        if (
            not isinstance(identifier, int)
            or identifier not in segments_by_id
            or identifier in findings_by_id
            or not isinstance(spans, list)
        ):
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency finding id/spans are invalid"
            )
        if finding_reason and finding_reason not in _FLUENCY_REASON_CODES:
            raise FluencyAuditFailed(
                "fluency_audit_failed: Hungarian fluency finding reason is invalid"
            )
        findings_by_id[identifier] = {
            "spans": spans,
            "reason": finding_reason,
        }

    # The model can occasionally contradict itself by marking a segment pass
    # while still returning exact findings for it.  Prefer concrete bounded
    # evidence when it also carries a valid reason; otherwise keep the text
    # unchanged and expose the segment as unresolved instead of degrading the
    # entire audit.
    effective_status_values = list(status_values)
    contradictory_unresolved_ids = set()
    for identifier, finding in findings_by_id.items():
        if effective_status_values[identifier] != "pass":
            continue
        finding_reason = finding.get("reason") or ""
        if finding_reason in _FLUENCY_REASON_CODES:
            effective_status_values[identifier] = finding_reason
        else:
            contradictory_unresolved_ids.add(identifier)

    parsed = []
    failed_sentence_ids = set()
    unresolved_sentence_ids = set()
    reason_codes = []
    raw_response_text = str(response_text or "")
    for identifier, status in enumerate(effective_status_values):
        if identifier in contradictory_unresolved_ids:
            failed_sentence_ids.add(identifier)
            unresolved_sentence_ids.add(identifier)
            continue
        if status == "pass":
            continue

        finding = findings_by_id.get(identifier) or {}
        spans = finding.get("spans")
        if not spans or len(spans) > _MAX_FLUENCY_SPANS_PER_SENTENCE:
            # Fluency is a quality-only audit. A model may classify a sentence
            # as bad yet omit exact evidence even under a structured schema.
            # Do not turn that inconsistency into a user-visible request
            # failure; keep the sentence untouched and expose it as unresolved.
            failed_sentence_ids.add(identifier)
            unresolved_sentence_ids.add(identifier)
            reason_codes.append(status)
            continue

        segment = segments_by_id[identifier]
        actionable = False
        protected_only = True
        for span in spans:
            if not isinstance(span, str) or not span or len(span) > _MAX_FLUENCY_SPAN_CHARS:
                raise FluencyAuditFailed(
                    "fluency_audit_failed: Hungarian fluency span is incomplete"
                )
            starts = [match.start() for match in re.finditer(re.escape(span), segment["text"])]
            if len(starts) != 1:
                raise FluencyAuditFailed(
                    "fluency_audit_failed: Hungarian fluency span is not exact within its sentence"
                )
            start = segment["start"] + starts[0]
            end = start + len(span)
            if _fluency_span_is_protected(raw_response_text, start, end, span, status):
                continue
            protected_only = False
            parsed.append({"start": start, "end": end, "text": span, "reason": status})
            actionable = True

        if actionable:
            failed_sentence_ids.add(identifier)
            reason_codes.append(status)
        elif not protected_only:
            failed_sentence_ids.add(identifier)
            unresolved_sentence_ids.add(identifier)
            reason_codes.append(status)
        # If every supplied span is protected (for example "machine learning"
        # or "Python"), normalize the auditor's false positive to pass. The
        # protected-term policy is deterministic and takes precedence over the
        # model classifier.

    failed_status_ids = {
        index for index, status in enumerate(effective_status_values) if status != "pass"
    }
    unresolved_sentence_ids.update(failed_status_ids - set(findings_by_id))
    unresolved_sentence_ids.update(contradictory_unresolved_ids)
    if len(parsed) > _MAX_FLUENCY_FINDINGS:
        raise FluencyAuditFailed(
            "fluency_audit_failed: Hungarian fluency findings are out of bounds"
        )
    return FluencyAuditResult(
        findings=tuple(parsed),
        sentences_audited=len(segments),
        sentences_failed=len(failed_sentence_ids),
        sentences_unresolved=len(unresolved_sentence_ids),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _run_hungarian_fluency_audit(
    client,
    model,
    user_text,
    response_text,
    *,
    constraints=None,
    control=None,
    trace=None,
    phase_callback=None,
):
    if _expected_language(user_text, constraints) != "hu":
        return FluencyAuditResult()
    if not bool(getattr(client, "supports_hungarian_fluency_audit", False)):
        return FluencyAuditResult()

    segments = _fluency_audit_segments(response_text)
    if not segments:
        return FluencyAuditResult()

    if trace is not None:
        trace.begin("hungarian_fluency_audit")
    if callable(phase_callback):
        phase_callback("Magyar folyékonyság ellenőrzése")
    call_kwargs = {
        "model": model,
        "messages": _fluency_audit_messages(segments),
        "num_predict": 512,
        "call_phase": "hungarian_fluency_audit",
        "response_format": _fluency_audit_response_schema(len(segments)),
    }
    if control is not None:
        call_kwargs["control"] = control
    try:
        audit = _parse_fluency_audit(
            _chat_once_compat(client, call_kwargs),
            response_text,
            segments,
        )
    except Exception as exc:
        if trace is not None:
            trace.end(
                "hungarian_fluency_audit",
                hungarian_fluency_audit_result="failed",
                fluency_audit_failure_reason=_bounded_response_evidence(str(exc), limit=220),
            )
        raise

    if trace is not None:
        trace.end(
            "hungarian_fluency_audit",
            hungarian_fluency_audit_result=(
                "partial"
                if audit.sentences_unresolved
                else ("repair_required" if audit.findings else "pass")
            ),
            fluency_audit_evidence=json.dumps(
                [item["text"] for item in audit.findings], ensure_ascii=False,
            ),
            fluency_audit_finding_count=len(audit.findings),
            fluency_sentences_audited=audit.sentences_audited,
            fluency_sentences_failed=audit.sentences_failed,
            fluency_sentences_unresolved=audit.sentences_unresolved,
            fluency_reason_codes=",".join(audit.reason_codes),
        )
    return audit


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
        "Unicode, malformed Hungarian morphology, agreement or inflection errors, duplicated "
        "morphology, broken local phrasing, semantic language corruption and malformed hybrid "
        "words while preserving the meaning. Preserve every number, "
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


def _fluency_repair_spans(response_text, findings):
    raw = str(response_text or "")
    merged_findings = []
    for item in sorted(findings, key=lambda value: (value["start"], value["end"])):
        start = int(item["start"])
        end = int(item["end"])
        if merged_findings and start < merged_findings[-1]["end"]:
            previous = merged_findings[-1]
            previous["end"] = max(previous["end"], end)
            previous["reasons"].append(str(item["reason"]))
            continue
        merged_findings.append({
            "start": start,
            "end": end,
            "reasons": [str(item["reason"])],
        })

    repairs = []
    for item in merged_findings:
        start = item["start"]
        end = item["end"]
        text = raw[start:end]
        if not text or len(text) > _MAX_REPAIR_SPAN_CHARS:
            raise FluencyAuditFailed(
                "fluency_audit_failed: fluent repair span is out of bounds"
            )
        repairs.append({
            "id": len(repairs),
            "start": start,
            "end": end,
            "text": text,
            "prefix": "",
            "suffix": "",
            "left_context": raw[max(0, start - 240):start],
            "right_context": raw[end:min(len(raw), end + 240)],
            "reason": ",".join(dict.fromkeys(item["reasons"])),
        })
    return repairs


def _merge_repair_spans(*span_groups):
    """Keep a deterministic invalid sentence over any nested fluency finding."""
    merged = []
    for candidate in sorted(
        (item for group in span_groups for item in group),
        key=lambda item: (item["start"], -(item["end"] - item["start"])),
    ):
        overlapping = [
            item for item in merged
            if candidate["start"] < item["end"] and item["start"] < candidate["end"]
        ]
        if not overlapping:
            merged.append(candidate)
            continue
        if any(
            item["start"] <= candidate["start"] and candidate["end"] <= item["end"]
            for item in overlapping
        ):
            continue
        if all(
            candidate["start"] <= item["start"] and item["end"] <= candidate["end"]
            for item in overlapping
        ):
            merged = [item for item in merged if item not in overlapping]
            merged.append(candidate)
            continue
        raise FluencyAuditFailed(
            "fluency_audit_failed: Hungarian fluency findings overlap ambiguously"
        )

    if len(merged) > _MAX_REPAIR_SPANS:
        raise FluencyAuditFailed(
            "fluency_audit_failed: too many bounded repair spans"
        )
    return [dict(item, id=index) for index, item in enumerate(
        sorted(merged, key=lambda item: item["start"])
    )]


def _repair_response_schema(spans):
    """Constrain bounded repairs to the smallest structured response Ollama can emit."""
    count = len(spans)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["repairs"],
        "properties": {
            "repairs": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "text"],
                    "properties": {
                        "id": {"type": "integer", "minimum": 0, "maximum": max(0, count - 1)},
                        "text": {"type": "string", "minLength": 1, "maxLength": _MAX_REPAIR_SPAN_CHARS},
                    },
                },
            },
        },
    }


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
            language_validation_evidence=_validation_evidence_json(validation),
        )

    try:
        fluency_audit = _run_hungarian_fluency_audit(
            client,
            model,
            user_text,
            draft,
            constraints=constraints,
            control=control,
            trace=trace,
            phase_callback=phase_callback,
        )
    except FluencyAuditFailed as exc:
        # The fluency audit is an editorial quality layer, not an authority or
        # safety gate. If its structured output is inconsistent, fail open for
        # fluency while preserving the deterministic language/script guard.
        # This prevents an optional quality check from discarding a complete
        # model answer or blocking deterministic CJK/language repair.
        if trace is not None:
            trace.add_metadata(
                hungarian_fluency_audit_result="degraded",
                fluency_audit_failure_reason=_bounded_response_evidence(str(exc), limit=220),
            )
        fluency_audit = FluencyAuditResult()
    if validation.valid and not fluency_audit.findings:
        return draft

    try:
        deterministic_spans = (
            _repair_spans(user_text, draft, constraints=constraints)
            if not validation.valid
            else []
        )
        spans = _merge_repair_spans(
            deterministic_spans,
            _fluency_repair_spans(draft, fluency_audit.findings),
        )
    except (LanguageRepairFailed, FluencyAuditFailed) as exc:
        raise _tag_repair_failure(
            exc,
            stage=(
                "hungarian_fluency_audit"
                if isinstance(exc, FluencyAuditFailed)
                else "language_validation"
            ),
            classification=(
                "fluency_audit_failed"
                if isinstance(exc, FluencyAuditFailed)
                else "language_repair_failed"
            ),
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
    # Use a strict schema rather than generic JSON mode. Gemma occasionally
    # keeps elaborating inside unconstrained JSON until the repair token cap is
    # reached even though only a few short spans need edits.
    call_kwargs["response_format"] = _repair_response_schema(spans)
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
        repair_result = _chat_once_compat(client, call_kwargs)
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
            evidence=repaired_validation.evidence,
        )
    if trace is not None:
        trace.end(
            "repair_integrity_validation",
            repair_integrity_result=("pass" if repaired and repaired_validation.valid else "failed"),
            repair_integrity_issues=",".join(repaired_validation.issues),
            repair_integrity_evidence=_validation_evidence_json(repaired_validation),
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
