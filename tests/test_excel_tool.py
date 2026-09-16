from pathlib import Path

from openpyxl import load_workbook

from app.excel_tool import (
    create_conversation_excel,
    create_structured_excel,
    sanitize_structured_payload,
)


def test_conversation_excel_created(tmp_path: Path):
    path = create_conversation_excel(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        title="Conversation Test",
        output_dir=tmp_path,
        model_name="qwen-test",
    )
    wb = load_workbook(path)
    ws = wb["Conversation"]

    assert ws["A1"].value == "Conversation Test"
    assert "qwen-test" in ws["A2"].value
    assert ws["A4"].value == "Role"
    assert ws.freeze_panes == "A5"


def test_structured_excel_from_json(tmp_path: Path):
    payload = (
        '{"title":"Model Comparison","sheets":['
        '{"name":"Models","headers":["Model","Status"],'
        '"rows":[["Qwen","Strong"],["Devstral","Good"]]}]}'
    )
    path = create_structured_excel(
        payload,
        output_dir=tmp_path,
        model_name="qwen-test",
    )
    wb = load_workbook(path)
    ws = wb["Models"]

    assert ws["A1"].value == "Model Comparison"
    assert "qwen-test" in ws["A2"].value
    assert ws["A4"].value == "Model"
    assert ws["A5"].value == "Qwen"
    assert ws["B5"].value == "Strong"


def test_long_headers_get_readable_column_widths(tmp_path: Path):
    payload = (
        '{"title":"Long Header Test","sheets":['
        '{"name":"Models","headers":['
        '"Model Name","Very Long Hardware Requirement Description"],'
        '"rows":[["Qwen","Not provided"]]}]}'
    )
    path = create_structured_excel(
        payload,
        output_dir=tmp_path,
    )
    wb = load_workbook(path)
    ws = wb["Models"]

    assert ws.column_dimensions["A"].width >= 14
    assert ws.column_dimensions["B"].width >= 30
    assert ws.column_dimensions["B"].width <= 42
    assert ws["B4"].alignment.wrap_text is True


def test_numeric_facts_not_in_source_are_replaced_hungarian():
    payload = {
        "title": "Modellek",
        "sheets": [{
            "name": "Modellek",
            "headers": ["Modell", "Kiadás éve", "RAM", "Megjegyzés"],
            "rows": [
                ["Phi-3", 2023, "16 GB", "Teszt"],
                ["Qwen", "Nincs megadva", "Nincs megadva", "Ok"],
            ],
        }],
    }

    sanitized = sanitize_structured_payload(
        payload,
        source_text=(
            "Készíts magyar táblázatot a helyi modellekről. "
            "Konkrét évszámot vagy RAM adatot nem adok meg."
        ),
    )
    row = sanitized["sheets"][0]["rows"][0]

    assert row[1] == "Nincs megadva"
    assert row[2] == "Nincs megadva"
    assert row[3] == "Teszt"


def test_numeric_fact_explicitly_in_source_is_preserved():
    payload = {
        "title": "Hardware",
        "sheets": [{
            "name": "Hardware",
            "headers": ["Model", "RAM"],
            "rows": [["Example", "32 GB"]],
        }],
    }

    sanitized = sanitize_structured_payload(
        payload,
        source_text="Use exactly 32 GB RAM for the Example model.",
    )

    assert sanitized["sheets"][0]["rows"][0][1] == "32 GB"


def test_zebra_rows_and_autofilter_are_applied(tmp_path: Path):
    payload = (
        '{"title":"Style Test","sheets":['
        '{"name":"Data","headers":["Name","Status"],'
        '"rows":[["A","One"],["B","Two"],["C","Three"]]}]}'
    )
    path = create_structured_excel(
        payload,
        output_dir=tmp_path,
    )
    wb = load_workbook(path)
    ws = wb["Data"]

    assert ws.auto_filter.ref == "A4:B7"
    assert ws.freeze_panes == "A5"
    assert ws.row_dimensions[4].height == 30
    assert ws.row_dimensions[5].height == 24
