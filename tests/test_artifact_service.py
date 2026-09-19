from pathlib import Path

import pytest

from app import artifact_service
from app.artifact_service import (
    ArtifactRequest,
    create_artifact,
    infer_artifact_format,
    infer_artifact_request,
    infer_artifact_requests,
)


@pytest.mark.parametrize(
    ("prompt", "expected_format", "expected_preset"),
    [
        (
            "Készíts nekem egy PDF fájlt Red Executive stílusban",
            "pdf",
            "Red Executive",
        ),
        (
            "Csinálj Word dokumentumot Classic Executive stílusban",
            "docx",
            "Classic Executive",
        ),
        (
            "Készíts Excel táblát ezekből az adatokból",
            "xlsx",
            "Red Executive Workbook",
        ),
        (
            "Create a Classic HTML report",
            "html",
            "Classic Professional",
        ),
        (
            "Készíts egy összefoglaló Markdown fájlt",
            "summary",
            "Local Summary",
        ),
    ],
)
def test_artifact_request_inference(prompt, expected_format, expected_preset):
    request = infer_artifact_request(prompt)

    assert request == ArtifactRequest(
        format=expected_format,
        preset=expected_preset,
    )


def test_artifact_inference_does_not_treat_plain_format_discussion_as_file_action():
    assert infer_artifact_format("Mi az a PDF?") == ""
    assert infer_artifact_request("Mire jó az Excel?") is None
    assert infer_artifact_request("Foglaljuk össze röviden a beszélgetést") is None


@pytest.mark.parametrize(
    ("fmt", "suffix"),
    [
        ("pdf", ".pdf"),
        ("docx", ".docx"),
        ("html", ".html"),
    ],
)
def test_document_artifact_service_routes_to_bounded_renderer(
    tmp_path: Path,
    monkeypatch,
    fmt,
    suffix,
):
    seen = {}

    def fake_renderer(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        path = Path(kwargs["output_dir"]) / f"result{suffix}"
        path.write_bytes(b"artifact")
        return path

    monkeypatch.setattr(artifact_service, f"create_{fmt}", fake_renderer)

    path = create_artifact(
        fmt,
        content="# Report\n\nBody",
        title="Report",
        preset="Red Executive",
        model_name="qwen",
        output_dir=tmp_path,
    )

    assert path == (tmp_path / f"result{suffix}").resolve()
    assert path.exists()
    assert seen["messages"] == [
        {"role": "assistant", "content": "# Report\n\nBody"}
    ]
    assert seen["kwargs"]["preset"] == "Red Executive"


def test_xlsx_artifact_service_uses_structured_renderer_for_generated_content(
    tmp_path: Path,
    monkeypatch,
):
    seen = {}

    def fake_structured(model_output, **kwargs):
        seen["model_output"] = model_output
        seen["kwargs"] = kwargs
        path = Path(kwargs["output_dir"]) / "result.xlsx"
        path.write_bytes(b"xlsx")
        return path

    monkeypatch.setattr(
        artifact_service,
        "create_structured_excel",
        fake_structured,
    )

    payload = '{"title":"Test","sheets":[]}'
    path = create_artifact(
        "xlsx",
        content=payload,
        title="Test",
        preset="Classic Workbook",
        model_name="qwen",
        source_text="source facts",
        output_dir=tmp_path,
    )

    assert path.suffix == ".xlsx"
    assert seen["model_output"] == payload
    assert seen["kwargs"]["source_text"] == "source facts"
    assert seen["kwargs"]["preset"] == "Classic Workbook"


def test_xlsx_artifact_service_uses_conversation_renderer_for_messages(
    tmp_path: Path,
    monkeypatch,
):
    seen = {}

    def fake_conversation(messages, **kwargs):
        seen["messages"] = messages
        path = Path(kwargs["output_dir"]) / "conversation.xlsx"
        path.write_bytes(b"xlsx")
        return path

    monkeypatch.setattr(
        artifact_service,
        "create_conversation_excel",
        fake_conversation,
    )

    messages = [{"role": "assistant", "content": "Hello"}]
    path = create_artifact(
        "xlsx",
        messages=messages,
        title="Conversation",
        output_dir=tmp_path,
    )

    assert path.suffix == ".xlsx"
    assert seen["messages"] == messages


def test_summary_artifact_is_utf8_markdown_inside_output_root(tmp_path: Path):
    path = create_artifact(
        "summary",
        content="# Összefoglaló\n\nLilla a lányod.",
        title="Személyes összefoglaló",
        output_dir=tmp_path,
    )

    assert path.suffix == ".md"
    assert path.parent == tmp_path.resolve()
    assert "Lilla a lányod." in path.read_text(encoding="utf-8")


def test_artifact_service_rejects_renderer_path_outside_output_root(
    tmp_path: Path,
    monkeypatch,
):
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"%PDF")

    monkeypatch.setattr(
        artifact_service,
        "create_pdf",
        lambda *args, **kwargs: outside,
    )

    with pytest.raises(RuntimeError, match="outside the LocalAI artifact output"):
        create_artifact(
            "pdf",
            content="# Test",
            output_dir=tmp_path,
        )


def test_artifact_service_rejects_unknown_format(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported artifact format"):
        create_artifact(
            "exe",
            content="nope",
            output_dir=tmp_path,
        )


def test_multiple_artifact_requests_are_planned_independently():
    prompt = """Készíts nekem egy Word dokumentumot Red Executive stílusban, amiben röviden összefoglalod, hogy ki nekem Lilla.

Készíts nekem egy Excel fájlt arról, hogy ki nekem Lilla.

Készíts nekem egy HTML riportot Classic Executive stílusban arról, hogy ki nekem Lilla.

Készíts nekem egy összefoglaló Markdown fájlt arról, hogy ki nekem Lilla."""

    plans = infer_artifact_requests(prompt)

    assert [(item.request.format, item.request.preset) for item in plans] == [
        ("docx", "Red Executive"),
        ("xlsx", "Red Executive Workbook"),
        ("html", "Classic Executive"),
        ("summary", "Local Summary"),
    ]
    assert all("Lilla" in item.prompt for item in plans)


def test_multiple_artifact_requests_on_one_line_split_at_repeated_creation_intent():
    prompt = (
        "Készíts Word dokumentumot Red Executive stílusban. "
        "Készíts Excel fájlt. "
        "Készíts HTML riportot Classic Executive stílusban."
    )

    plans = infer_artifact_requests(prompt)

    assert [(item.request.format, item.request.preset) for item in plans] == [
        ("docx", "Red Executive"),
        ("xlsx", "Red Executive Workbook"),
        ("html", "Classic Executive"),
    ]


def test_artifact_preset_does_not_leak_between_neighboring_requests():
    prompt = (
        "Készíts Excel fájlt az adatokról. "
        "Készíts HTML riportot Classic Executive stílusban."
    )

    plans = infer_artifact_requests(prompt)

    assert plans[0].request.format == "xlsx"
    assert plans[0].request.preset == "Red Executive Workbook"
    assert plans[1].request.format == "html"
    assert plans[1].request.preset == "Classic Executive"

