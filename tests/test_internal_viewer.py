import inspect
from pathlib import Path

from docx import Document
from openpyxl import Workbook

from app.internal_viewer import (
    classify_resource,
    convert_docx_to_pdf_preview,
    pdf_text_fallback,
    render_docx_html,
    resource_identity,
    resource_title,
    save_resource_copy,
    spreadsheet_preview,
)


def test_resource_classifier_routes_web_and_supported_artifacts():
    assert classify_resource("https://example.com/report") == "browser"
    assert classify_resource(Path("report.html")) == "html"
    assert classify_resource(Path("report.pdf")) == "pdf"
    assert classify_resource(Path("report.docx")) == "docx"
    assert classify_resource(Path("report.xlsx")) == "spreadsheet"
    assert classify_resource(Path("report.csv")) == "spreadsheet"
    assert classify_resource(Path("report.md")) == "markdown"
    assert classify_resource(Path("report.txt")) == "text"
    assert classify_resource(Path("image.png")) == "image"


def test_resource_title_uses_host_or_file_name():
    assert resource_title("https://example.com/") == "example.com"
    assert resource_title("https://example.com/path/report") == "report"
    assert resource_title(Path("C:/tmp/report.pdf")) == "report.pdf"


def test_docx_preview_preserves_heading_paragraph_and_table(tmp_path):
    path = tmp_path / "report.docx"
    document = Document()
    document.add_heading("Executive Summary", level=1)
    document.add_paragraph("A concise document preview.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "Value"
    document.save(path)

    rendered = render_docx_html(path)

    assert "<h1>Executive Summary</h1>" in rendered
    assert "A concise document preview." in rendered
    assert "Metric" in rendered
    assert "Value" in rendered


def test_spreadsheet_preview_reads_multiple_sheets(tmp_path):
    path = tmp_path / "book.xlsx"
    workbook = Workbook()
    first = workbook.active
    first.title = "Summary"
    first.append(["Name", "Value"])
    first.append(["BTC", 100])

    second = workbook.create_sheet("Notes")
    second.append(["Status"])
    second.append(["PASS"])
    workbook.save(path)

    preview = spreadsheet_preview(path)

    assert [item["name"] for item in preview] == ["Summary", "Notes"]
    assert preview[0]["rows"][1] == ["BTC", "100"]
    assert preview[1]["rows"][1] == ["PASS"]


def test_spreadsheet_preview_is_bounded(tmp_path):
    path = tmp_path / "large.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for index in range(10):
        sheet.append([index, index + 1, index + 2])
    workbook.save(path)

    preview = spreadsheet_preview(path, max_rows=3, max_columns=2)

    assert len(preview[0]["rows"]) == 3
    assert len(preview[0]["rows"][0]) == 2
    assert preview[0]["truncated"] is True


def test_resource_identity_normalizes_files_and_preserves_web_urls():
    url = "https://example.com/path?q=1"
    assert resource_identity(url) == url
    assert resource_identity(Path("report.pdf")) == str(Path("report.pdf").resolve())


def test_spreadsheet_preview_reads_csv_cells(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("Name,Value\nBTC,100\nETH,200\n", encoding="utf-8")

    preview = spreadsheet_preview(path)

    assert preview[0]["name"] == "data"
    assert preview[0]["rows"][0] == ["Name", "Value"]
    assert preview[0]["rows"][1] == ["BTC", "100"]
    assert preview[0]["rows"][2] == ["ETH", "200"]


def test_pdf_text_fallback_extracts_text_and_marks_truncation(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        pages = [Page("First page"), Page("Second page")]

    monkeypatch.setattr("app.internal_viewer.PdfReader", lambda _path: Reader())

    rendered = pdf_text_fallback("ignored.pdf", max_pages=1)

    assert "--- PAGE 1 ---" in rendered
    assert "First page" in rendered
    assert "Second page" not in rendered
    assert "[PDF preview truncated]" in rendered


def test_docx_view_uses_light_document_surface_in_dark_app_theme():
    from app.internal_viewer import DocumentView

    source = inspect.getsource(DocumentView.__init__)

    assert "background:#FFFFFF" in source
    assert "color:#20242A" in source
    assert "view.setHtml(render_docx_html(path))" in source


def test_save_resource_copy_preserves_local_artifact_bytes(tmp_path):
    source = tmp_path / "source.docx"
    source.write_bytes(b"local-ai-artifact")
    destination = tmp_path / "exports" / "saved.docx"

    result = save_resource_copy(source, destination)

    assert result == destination.resolve()
    assert destination.read_bytes() == b"local-ai-artifact"


def test_requested_document_viewers_expose_shared_save_as_action():
    from app.internal_viewer import (
        DocumentView,
        MarkdownTextView,
        PdfViewWidget,
        SpreadsheetView,
    )

    for viewer in (PdfViewWidget, DocumentView, SpreadsheetView, MarkdownTextView):
        source = inspect.getsource(viewer.__init__)
        assert "_add_save_as_toolbar(root, path, self)" in source


def test_save_as_dialog_defaults_to_downloads_and_preserves_extension():
    from app import internal_viewer

    source = inspect.getsource(internal_viewer._save_resource_as_dialog)
    default_source = inspect.getsource(internal_viewer._default_save_path)

    assert 'Path.home() / "Downloads"' in default_source
    assert '"Save As"' in source
    assert "source.suffix" in source
    assert "save_resource_copy(source, destination)" in source


def test_docx_pdf_preview_uses_headless_libreoffice_contract(tmp_path, monkeypatch):
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx")
    output_dir = tmp_path / "preview"
    executable = tmp_path / "soffice.exe"
    executable.write_bytes(b"exe")
    captured = {}

    class Completed:
        returncode = 0

    def fake_run(**kwargs):
        captured.update(kwargs)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.pdf").write_bytes(b"%PDF-preview")
        return Completed()

    monkeypatch.setattr("app.internal_viewer.subprocess.run", fake_run)

    result = convert_docx_to_pdf_preview(
        source,
        output_dir,
        executable=executable,
    )

    assert result == (output_dir / "report.pdf").resolve()
    assert "--headless" in captured["args"]
    assert "--convert-to" in captured["args"]
    assert "pdf" in captured["args"]
    assert "--outdir" in captured["args"]
    assert str(source.resolve()) in captured["args"]
    assert captured["timeout"] == 45


def test_docx_pdf_preview_returns_none_when_libreoffice_is_unavailable(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx")
    monkeypatch.setattr(
        "app.internal_viewer.find_libreoffice_executable",
        lambda: None,
    )

    assert convert_docx_to_pdf_preview(source, tmp_path / "preview") is None


def test_docx_view_prefers_rendered_pdf_and_keeps_basic_fallback():
    from app.internal_viewer import DocumentView

    source = inspect.getsource(DocumentView.__init__)

    assert "convert_docx_to_pdf_preview(" in source
    assert "High-fidelity DOCX preview" in source
    assert "PdfViewWidget(" in source
    assert "show_save_as=False" in source
    assert "Basic DOCX preview" in source
    assert "render_docx_html(path)" in source
