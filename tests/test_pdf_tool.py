from pathlib import Path

from app.pdf_tool import create_red_professional_pdf, markdown_to_reportlab


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
