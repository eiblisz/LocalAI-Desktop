import re
from dataclasses import dataclass

from .language_policy import (
    effective_response_language,
    repair_preserves_factual_literals,
    response_language_matches,
    response_validation_text,
)
from .task_constraints import TaskConstraints


class ResponseValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResponseValidation:
    valid: bool
    expected_language: str
    issues: tuple[str, ...] = ()


_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)

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


def validate_response(user_text, response_text, constraints=None):
    expected = _expected_language(user_text, constraints)
    issues = list(unexpected_script_issues(user_text, response_text, constraints))

    if expected in {"hu", "de", "en"} and not response_language_matches(
        user_text,
        response_text,
    ):
        issues.append("language_mismatch")

    return ResponseValidation(
        valid=not issues,
        expected_language=expected,
        issues=tuple(dict.fromkeys(issues)),
    )


def _language_name(language):
    return {
        "hu": "Hungarian",
        "de": "German",
        "en": "English",
    }.get(language, "the language requested by the user")


def _repair_messages(user_text, response_text, validation, constraints=None):
    parent_intent = ""
    if isinstance(constraints, TaskConstraints):
        parent_intent = str(constraints.parent_intent or "").strip()

    system = (
        "Repair the supplied draft without changing its meaning or factual content. "
        f"Write the entire final answer in {_language_name(validation.expected_language)}. "
        "Remove accidental foreign-script leakage that is not required by the user. "
        "Preserve every URL, number, date, currency value, product/model name, proper name, "
        "and factual claim exactly. Preserve the original structure when possible. "
        "Do not add new facts, examples, recommendations, or explanations. "
        "Return only the repaired answer."
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
                + "\n\nDRAFT TO REPAIR:\n"
                + str(response_text or "")
            ),
        },
    ]


def guard_response(
    client,
    model,
    user_text,
    response_text,
    *,
    constraints=None,
    control=None,
    output_budget=None,
):
    """
    Validate one final model response and perform at most one bounded repair.

    The invalid original draft is never returned to the caller.
    """
    draft = str(response_text or "").strip()
    if not draft:
        return draft

    validation = validate_response(
        user_text,
        draft,
        constraints=constraints,
    )
    if validation.valid:
        return draft

    repair_messages = _repair_messages(
        user_text,
        draft,
        validation,
        constraints=constraints,
    )
    call_kwargs = {"model": model, "messages": repair_messages}
    if control is not None:
        call_kwargs["control"] = control
    if output_budget is not None:
        call_kwargs["num_predict"] = int(output_budget)
    while True:
        try:
            repaired = client.chat_once(**call_kwargs).strip()
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
            raise

    repaired_validation = validate_response(
        user_text,
        repaired,
        constraints=constraints,
    )
    if not repair_preserves_factual_literals(draft, repaired):
        repaired_validation = ResponseValidation(
            valid=False,
            expected_language=repaired_validation.expected_language,
            issues=tuple(dict.fromkeys(
                repaired_validation.issues + ("factual_literal_changed",)
            )),
        )
    if repaired and repaired_validation.valid:
        return repaired

    raise ResponseValidationError(
        "Response rejected after one bounded language/script repair attempt: "
        + ", ".join(repaired_validation.issues or validation.issues)
    )
