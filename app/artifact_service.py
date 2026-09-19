from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import OUTPUT_DIR
from .docx_tool import create_docx
from .excel_tool import create_conversation_excel, create_structured_excel
from .html_tool import create_html
from .pdf_tool import create_pdf


SUPPORTED_ARTIFACT_FORMATS = ("pdf", "docx", "xlsx", "html", "summary")


@dataclass(frozen=True)
class ArtifactRequest:
    format: str
    preset: str


def _fold(text: str) -> str:
    return " ".join(str(text or "").strip().casefold().split())


def _has_creation_intent(text: str) -> bool:
    normalized = _fold(text)
    markers = (
        "készíts",
        "keszits",
        "csinálj",
        "csinalj",
        "hozz létre",
        "hozz letre",
        "generálj",
        "generalj",
        "mentsd",
        "save",
        "create",
        "make",
        "generate",
        "export",
    )
    return any(marker in normalized for marker in markers)


def infer_artifact_format(text: str) -> str:
    normalized = _fold(text)
    if not normalized or not _has_creation_intent(normalized):
        return ""

    if re.search(r"\b(pdf)\b", normalized):
        return "pdf"
    if re.search(r"\b(xlsx|excel)\b", normalized) or "munkafüzet" in normalized:
        return "xlsx"
    if re.search(r"\b(html)\b", normalized) or "weboldal" in normalized:
        return "html"

    summary_markers = (
        "összefoglaló",
        "osszefoglalo",
        "összesítő",
        "osszesito",
        "summary",
        "brief",
    )
    file_markers = (
        "fájl",
        "fajl",
        "dokumentum",
        "markdown",
        ".md",
        "file",
    )
    if (
        any(marker in normalized for marker in summary_markers)
        and any(marker in normalized for marker in file_markers)
    ):
        return "summary"

    if (
        re.search(r"\b(doc|docx|word)\b", normalized)
        or "word dokument" in normalized
        or "dokumentum" in normalized
    ):
        return "docx"

    return ""


def _document_preset(text: str) -> str:
    normalized = _fold(text)
    if "classic executive" in normalized:
        return "Classic Executive"
    if "classic professional" in normalized:
        return "Classic Professional"
    if "red executive" in normalized:
        return "Red Executive"
    if "red professional" in normalized:
        return "Red Professional"
    if "classic" in normalized:
        return "Classic Professional"
    return "Red Professional"


def _workbook_preset(text: str) -> str:
    normalized = _fold(text)
    if "classic" in normalized:
        return "Classic Workbook"
    return "Red Executive Workbook"


def infer_artifact_request(text: str) -> ArtifactRequest | None:
    artifact_format = infer_artifact_format(text)
    if not artifact_format:
        return None

    if artifact_format == "xlsx":
        preset = _workbook_preset(text)
    elif artifact_format == "summary":
        preset = "Local Summary"
    else:
        preset = _document_preset(text)

    return ArtifactRequest(format=artifact_format, preset=preset)


def _safe_stem(title: str) -> str:
    clean = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ _-]+", "", str(title or "")).strip()
    clean = re.sub(r"\s+", "_", clean)
    return (clean[:72] or "local_ai_summary").strip("_")


def _validate_output_path(path: Path, output_dir: Path) -> Path:
    resolved_dir = Path(output_dir).resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(resolved_dir)
    except ValueError as exc:
        raise RuntimeError(
            "Artifact renderer returned a path outside the LocalAI artifact output directory."
        ) from exc
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError("Artifact renderer did not produce a file.")
    return resolved


def create_artifact(
    artifact_format: str,
    *,
    title: str = "Local AI Document",
    preset: str = "",
    messages: list[dict] | None = None,
    content: str = "",
    source_text: str = "",
    model_name: str = "",
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    """
    Render one bounded LocalAI artifact into output_dir.

    This service is intentionally file-creation-only. It never opens arbitrary paths,
    never deletes files, and never executes shell commands.
    """
    fmt = str(artifact_format or "").strip().casefold()
    if fmt not in SUPPORTED_ARTIFACT_FORMATS:
        raise ValueError(f"Unsupported artifact format: {artifact_format}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered_messages = list(messages or [])
    if content:
        rendered_messages = [{"role": "assistant", "content": str(content)}]

    if fmt == "pdf":
        path = create_pdf(
            rendered_messages,
            title=title,
            preset=preset or "Red Professional",
            output_dir=output_dir,
        )
    elif fmt == "docx":
        path = create_docx(
            rendered_messages,
            title=title,
            preset=preset or "Red Professional",
            model_name=model_name,
            output_dir=output_dir,
        )
    elif fmt == "html":
        path = create_html(
            rendered_messages,
            title=title,
            preset=preset or "Red Professional",
            output_dir=output_dir,
        )
    elif fmt == "xlsx":
        if content:
            path = create_structured_excel(
                content,
                title=title,
                source_text=source_text,
                model_name=model_name,
                preset=preset or "Red Executive Workbook",
                output_dir=output_dir,
            )
        else:
            path = create_conversation_excel(
                rendered_messages,
                title=title,
                model_name=model_name,
                preset=preset or "Red Executive Workbook",
                output_dir=output_dir,
            )
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{_safe_stem(title)}_{stamp}.md"
        body = str(content or "").strip()
        if not body and rendered_messages:
            body = "\n\n".join(
                str(item.get("content", "")).strip()
                for item in rendered_messages
                if str(item.get("role", "")).lower() in {"user", "assistant"}
                and str(item.get("content", "")).strip()
            )
        if not body:
            raise RuntimeError("Summary artifact content is empty.")
        path.write_text(body + "\n", encoding="utf-8")

    return _validate_output_path(Path(path), output_dir)
