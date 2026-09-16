from pathlib import Path

from docx import Document

from app.docx_tool import (
    create_red_executive_docx,
    create_red_professional_docx,
)


def test_red_professional_docx_created(tmp_path: Path):
    path = create_red_professional_docx(
        [{"role": "assistant", "content": "# Test\n## Section\nBody text."}],
        title="Fallback",
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.suffix == ".docx"
    doc = Document(path)
    assert len(doc.paragraphs) >= 1


def test_red_executive_docx_created(tmp_path: Path):
    path = create_red_executive_docx(
        [{"role": "assistant", "content": "# Executive Test\nBody text."}],
        output_dir=tmp_path,
    )
    assert path.exists()
    assert path.name.startswith("local_ai_executive_")


def test_hungarian_red_executive_docx_localizes_fixed_labels(tmp_path: Path):
    path = create_red_executive_docx(
        [{
            "role": "assistant",
            "content": (
                "# Magyar helyi AI riport\n"
                "Ez egy magyar dokumentum a helyi modellekről és adatokról."
            ),
        }],
        output_dir=tmp_path,
    )
    doc = Document(path)
    table_text = "\n".join(
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    )
    assert "Vezetői összefoglaló" in table_text
    assert "Futtatás" in table_text
    assert "Készült" in table_text


def test_docx_markdown_table_becomes_real_word_table(tmp_path: Path):
    path = create_red_executive_docx(
        [{
            "role": "assistant",
            "content": (
                "# Táblázat teszt\n"
                "## Összehasonlítás\n"
                "| Tulajdonság | Lokális AI | Felhőalapú AI |\n"
                "| --- | --- | --- |\n"
                "| Adatvédelem | Magas | Alacsony |\n"
                "| Offline működés | Igen | Nem |\n"
            ),
        }],
        output_dir=tmp_path,
        model_name="qwen-test",
    )
    doc = Document(path)

    all_cell_text = [
        cell.text
        for table in doc.tables
        for row in table.rows
        for cell in row.cells
    ]
    assert "Tulajdonság" in all_cell_text
    assert "Adatvédelem" in all_cell_text
    assert not any("| --- |" in paragraph.text for paragraph in doc.paragraphs)


def test_docx_footer_is_small_and_contains_model(tmp_path: Path):
    path = create_red_executive_docx(
        [{
            "role": "assistant",
            "content": "# Magyar riport\nEz egy magyar dokumentum a helyi modellekről.",
        }],
        output_dir=tmp_path,
        model_name="qwen3-coder:30b-a3b-q8_0",
    )
    doc = Document(path)
    footer = doc.sections[0].footer.paragraphs[0]
    text = footer.text

    assert "qwen3-coder:30b-a3b-q8_0" in text
    assert "Készült:" in text
    assert footer.runs
    assert footer.runs[0].font.size.pt <= 8


def test_bullet_markdown_bold_is_rendered(tmp_path: Path):
    path = create_red_professional_docx(
        [{
            "role": "assistant",
            "content": "# Lista\n- **Adatvédelem**: fontos előny",
        }],
        output_dir=tmp_path,
    )
    doc = Document(path)
    bullet = next(p for p in doc.paragraphs if "Adatvédelem" in p.text)
    assert "**" not in bullet.text
    assert any(run.bold and "Adatvédelem" in run.text for run in bullet.runs)
