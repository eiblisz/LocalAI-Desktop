from pathlib import Path

from app.html_tool import create_red_html


def test_red_executive_html_created(tmp_path: Path):
    path = create_red_html(
        [{"role": "assistant", "content": "# HTML Test\n## Section\nBody"}],
        executive=True,
        output_dir=tmp_path,
    )
    content = path.read_text(encoding="utf-8")
    assert path.exists()
    assert "RED EXECUTIVE REPORT" in content
    assert "HTML Test" in content
    assert "<style>" in content
