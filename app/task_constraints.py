from dataclasses import dataclass
import re

from .language_policy import (
    detect_user_language,
    effective_response_language,
    explicit_response_language,
)
from .generation_policy import (
    output_budget_for_response_length,
    requested_response_length,
)
from .request_semantics import classify_request


@dataclass(frozen=True)
class TaskConstraints:
    response_language: str
    output_style: str
    forbidden_language_drift: bool
    parent_intent: str
    format_constraints: tuple[str, ...] = ()
    user_explicit_constraints: tuple[str, ...] = ()
    request_profile: object = None
    explicit_batch_child: bool = False
    response_length: str = "normal"
    output_budget: int = 1024


def _clean(text):
    return " ".join(str(text or "").split())


def _explicit_constraints(text):
    raw = str(text or "")
    folded = raw.casefold()
    constraints = []

    markers = (
        ("kizárólag magyarul", "answer only in Hungarian"),
        ("kizarolag magyarul", "answer only in Hungarian"),
        ("csak magyarul", "answer only in Hungarian"),
        ("magyarul válaszolj", "answer in Hungarian"),
        ("magyarul valaszolj", "answer in Hungarian"),
        ("respond only in english", "answer only in English"),
        ("answer only in english", "answer only in English"),
        ("nur auf deutsch", "answer only in German"),
        ("antworte nur auf deutsch", "answer only in German"),
    )
    for marker, canonical in markers:
        if marker in folded and canonical not in constraints:
            constraints.append(canonical)

    for match in re.finditer(
        r"(?im)^\s*(?:[-*]|\d{1,2}[.)])?\s*"
        r"((?:ne|don't|do not|nicht)\b[^\n]{1,220})$",
        raw,
    ):
        value = _clean(match.group(1))
        if value and value not in constraints:
            constraints.append(value)

    return tuple(constraints[:12])


def _format_constraints(text):
    raw = str(text or "")
    folded = raw.casefold()
    result = []

    markers = (
        ("táblázat", "table"),
        ("tablazat", "table"),
        ("bullet", "bulleted list"),
        ("felsorolás", "bulleted list"),
        ("felsorolas", "bulleted list"),
        ("json", "JSON"),
        ("markdown", "Markdown"),
        ("html", "HTML"),
        ("rövid", "concise"),
        ("rovid", "concise"),
        ("részletes", "detailed"),
        ("reszletes", "detailed"),
    )
    for marker, canonical in markers:
        if marker in folded and canonical not in result:
            result.append(canonical)

    paragraph_range = re.search(
        r"(?i)\b(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*"
        r"(?:bekezdés(?:es)?|bekezdes(?:es)?|paragraphs?|absätze?|absatze?)\b",
        raw,
    )
    if paragraph_range:
        low, high = sorted((int(paragraph_range.group(1)), int(paragraph_range.group(2))))
        result.append(f"{low}-{high} paragraphs")
    else:
        paragraph_count = re.search(
            r"(?i)\b(?:legalább\s+|legalabb\s+|at least\s+|mindestens\s+)?"
            r"(\d{1,2})\s*(?:bekezdés(?:es)?|bekezdes(?:es)?|paragraphs?|absätze?|absatze?)\b",
            raw,
        )
        if paragraph_count:
            result.append(f"{int(paragraph_count.group(1))} paragraphs")

    return tuple(dict.fromkeys(result))[:8]


def build_task_constraints(
    user_text,
    *,
    parent_text="",
    explicit_batch_child=False,
):
    parent = _clean(user_text)
    canonical_parent = _clean(parent_text) or parent
    current_language = (
        explicit_response_language(parent)
        or detect_user_language(parent)
    )
    language = (
        current_language
        if current_language in {"hu", "de", "en"}
        else effective_response_language(canonical_parent)
    )
    output_style = (
        "natural_hungarian"
        if language == "hu"
        else (
            "natural_german"
            if language == "de"
            else ("natural_english" if language == "en" else "match_user_language")
        )
    )
    profile = classify_request(parent)
    response_length = requested_response_length(parent, profile=profile)
    return TaskConstraints(
        response_language=language,
        output_style=output_style,
        forbidden_language_drift=True,
        parent_intent=(
            parent[:2400]
            if explicit_batch_child
            else canonical_parent[:2400]
        ),
        format_constraints=_format_constraints(canonical_parent),
        user_explicit_constraints=_explicit_constraints(canonical_parent),
        request_profile=profile,
        explicit_batch_child=bool(explicit_batch_child),
        response_length=response_length,
        output_budget=output_budget_for_response_length(response_length),
    )


def task_constraints_instruction(constraints, *, current_subtask=""):
    if not isinstance(constraints, TaskConstraints):
        return ""

    language_name = {
        "hu": "Hungarian",
        "de": "German",
        "en": "English",
    }.get(constraints.response_language, "the same language as the parent user request")

    lines = [
        "TASK CONSTRAINTS:",
        f"- Expected response language: {language_name}.",
        f"- Output style: {constraints.output_style}.",
        "- Language drift is forbidden unless the user explicitly requests a language change.",
    ]
    if constraints.explicit_batch_child:
        lines.extend([
            "- This is an explicit batch child; answer it as an independent subtask.",
            "- Do not use sibling subjects or entities as factual context or guard authority.",
        ])
    else:
        lines.extend([
            "- Preserve the parent task's subject, entities, goal, prohibitions, and format constraints.",
            "- Treat the current subtask as part of the parent task, not as an unrelated standalone topic.",
            f"- Parent task: {constraints.parent_intent}",
        ])

    subtask = _clean(current_subtask)
    if subtask:
        lines.append(f"- Current subtask: {subtask[:1200]}")

    if constraints.format_constraints:
        lines.append(
            "- Format constraints: " + ", ".join(constraints.format_constraints)
        )
    profile = getattr(constraints, "request_profile", None)
    if profile is not None:
        lines.extend([
            f"- Request kind: {getattr(profile, 'kind', 'general')}.",
            f"- Response depth: {getattr(profile, 'response_depth', 'standard')}.",
            f"- Research breadth: {getattr(profile, 'research_breadth', 'balanced')}.",
        ])
    lines.extend([
        f"- Requested response length: {constraints.response_length}.",
        f"- Output budget: {constraints.output_budget}.",
        "- If the user requests a paragraph count or range, obey it as a hard structural constraint; headings and list items do not count as extra paragraphs unless explicitly requested.",
        "- Do not append a Sources/Források/References section unless verified source evidence is present in the task context or the user explicitly asks for source attribution.",
        "- In normal prose, do not emit HTML space entities such as &#x20; or &#32;.",
    ])

    if constraints.user_explicit_constraints:
        lines.append(
            "- Explicit user constraints: "
            + " | ".join(constraints.user_explicit_constraints)
        )

    return "\n".join(lines)
