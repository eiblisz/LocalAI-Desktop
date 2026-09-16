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
    assert content.count("<h1>") == 1


def test_hungarian_html_localizes_fixed_labels_and_deduplicates_title(tmp_path: Path):
    path = create_red_html(
        [{
            "role": "assistant",
            "content": (
                "# Összehasonlító táblázat lokális coding modellekről\n"
                "## Bevezetés\n"
                "Ez egy magyar nyelvű dokumentum a helyi modellekről és adatokról."
            ),
        }],
        executive=True,
        output_dir=tmp_path,
    )
    content = path.read_text(encoding="utf-8")
    assert content.count("<h1>") == 1
    assert "Vezetői összefoglaló" in content
    assert "Futtatás" in content
    assert "Készült" in content
    assert 'lang="hu"' in content
