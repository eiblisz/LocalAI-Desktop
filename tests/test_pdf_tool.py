from pathlib import Path

from app.pdf_tool import create_red_professional_pdf


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
