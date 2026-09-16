from pathlib import Path

from pypdf import PdfReader

from app.pdf_tool import (
    create_red_executive_pdf,
    create_red_professional_pdf,
    markdown_to_reportlab,
)


def test_pdf_created(tmp_path: Path):
    messages = [
        {"role": "user", "content": "Create a report."},
        {"role": "assistant", "content": "Report content."},
    ]
    path = create_red_professional_pdf(
        messages,
        title="Test Report",
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.stat().st_size > 500


def test_red_executive_pdf_created(tmp_path: Path):
    messages = [
        {
            "role": "assistant",
            "content": (
                "# Local AI Development System\n"
                "## Executive Summary\n"
                "A structured local model report.\n\n"
                "Source Generation: 90%\n"
                "Syntax Correctness: 95%\n\n"
                "| Model | Result |\n"
                "| --- | --- |\n"
                "| Qwen | Strong |"
            ),
        }
    ]
    path = create_red_executive_pdf(
        messages,
        title="Fallback title",
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.name.startswith("local_ai_executive_")
    assert path.stat().st_size > 1000


def test_hungarian_red_executive_pdf_localizes_fixed_labels(tmp_path: Path):
    path = create_red_executive_pdf(
        [{
            "role": "assistant",
            "content": (
                "# Magyar helyi AI riport\n"
                "Ez egy magyar dokumentum a helyi modellekről és adatokról."
            ),
        }],
        output_dir=tmp_path,
    )
    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(str(path)).pages
    )
    assert "Vezetői összefoglaló" in text
    assert "Futtatás" in text
    assert "Készült" in text


def test_markdown_bold_is_rendered_for_reportlab():
    rendered = markdown_to_reportlab("This is **important**.")
    assert "<b>important</b>" in rendered
    assert "**important**" not in rendered


def test_artifact_messages_are_not_required_for_pdf(tmp_path: Path):
    messages = [
        {"role": "assistant", "content": "# Title\n**Bold text**"},
        {
            "role": "artifact",
            "content": "PDF created",
            "path": "C:/tmp/old.pdf",
        },
    ]
    path = create_red_professional_pdf(
        messages,
        title="Markdown Test",
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.stat().st_size > 500
