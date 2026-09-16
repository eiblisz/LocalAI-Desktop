import json
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .artifact_themes import get_theme
from .config import OUTPUT_DIR
from .localization import is_hungarian

FACTUAL_HEADER_MARKERS = (
    "year", "release", "date", "kiadás", "megjelenés", "dátum",
    "benchmark", "score", "pont", "accuracy", "pontosság",
    "percent", "százalék", "%",
    "ram", "vram", "gpu", "cpu", "storage", "tárhely",
    "price", "ár", "cost", "költség",
    "parameter", "paraméter", "capacity", "kapacitás",
    "context", "token", "latency", "késleltetés", "speed", "sebesség",
)


def _clean_json(text):
    stripped = text.strip()
    fence = chr(96) * 3
    if stripped.startswith(fence):
        stripped = stripped[len(fence):].lstrip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    if stripped.endswith(fence):
        stripped = stripped[:-len(fence)].rstrip()
    return json.loads(stripped)


def _safe_sheet_name(name):
    clean = re.sub(r"[:\\/?*\[\]]", "-", str(name)).strip() or "Sheet"
    return clean[:31]


def _normalize_for_match(value):
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _header_requires_source(header):
    h = _normalize_for_match(header)
    return any(marker in h for marker in FACTUAL_HEADER_MARKERS)


def _numeric_tokens(value):
    return re.findall(r"\d+(?:[.,]\d+)?", str(value))


def _is_unknown_value(value):
    normalized = _normalize_for_match(value)
    return normalized in {
        "", "unknown", "not provided", "n/a", "na",
        "nincs megadva", "ismeretlen", "nem ismert",
    }


def sanitize_structured_payload(payload, source_text=""):
    source = _normalize_for_match(source_text)
    missing = "Nincs megadva" if is_hungarian(source_text) else "Not provided"

    sheets = payload.get("sheets") or []
    for sheet in sheets:
        headers = list(sheet.get("headers") or [])
        rows = sheet.get("rows") or []

        protected = {
            index
            for index, header in enumerate(headers)
            if _header_requires_source(header)
        }

        if not protected:
            continue

        for row in rows:
            if not isinstance(row, list):
                continue
            for index in protected:
                if index >= len(row):
                    continue

                value = row[index]
                if value is None or _is_unknown_value(value):
                    continue

                tokens = _numeric_tokens(value)
                if not tokens:
                    continue

                if not source:
                    row[index] = missing
                    continue

                unsupported = [
                    token
                    for token in tokens
                    if token.replace(",", ".") not in source.replace(",", ".")
                ]
                if unsupported:
                    row[index] = missing

    return payload


def _style_sheet(
    ws,
    title,
    theme,
    columns=1,
    model_name="",
    source_label="Custom topic",
):
    ws.sheet_view.showGridLines = False
    end_col = max(1, columns)

    ws.merge_cells(
        start_row=1,
        start_column=1,
        end_row=1,
        end_column=end_col,
    )
    ws["A1"] = title
    ws["A1"].font = Font(
        name="Arial",
        size=20,
        bold=True,
        color=theme.hero_foreground,
    )
    ws["A1"].fill = PatternFill("solid", fgColor=theme.accent_dark)
    ws["A1"].alignment = Alignment(
        vertical="center",
        horizontal="left",
        wrap_text=True,
    )
    ws.row_dimensions[1].height = 38

    ws.merge_cells(
        start_row=2,
        start_column=1,
        end_row=2,
        end_column=end_col,
    )
    meta = (
        f"{theme.label}  ·  "
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if model_name:
        meta += f"  ·  Model: {model_name}"
    if source_label:
        meta += f"  ·  Source: {source_label}"

    ws["A2"] = meta
    ws["A2"].font = Font(
        name="Arial",
        size=9,
        italic=True,
        color=theme.muted,
    )
    ws["A2"].fill = PatternFill("solid", fgColor=theme.surface)
    ws["A2"].alignment = Alignment(
        vertical="center",
        horizontal="left",
        wrap_text=True,
    )
    ws.row_dimensions[2].height = 22

    ws.freeze_panes = "A5"
    ws.print_options.horizontalCentered = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _style_table(ws, theme, header_row=4):
    thin = Side(style="thin", color=theme.border)

    for cell in ws[header_row]:
        if cell.value is not None:
            cell.font = Font(
                name="Arial",
                size=11,
                bold=True,
                color=theme.hero_foreground,
            )
            cell.fill = PatternFill("solid", fgColor=theme.accent)
            cell.alignment = Alignment(
                vertical="center",
                horizontal="left",
                wrap_text=True,
            )
            cell.border = Border(
                top=thin,
                bottom=thin,
                left=thin,
                right=thin,
            )
    ws.row_dimensions[header_row].height = 30

    for row_index, row in enumerate(
        ws.iter_rows(min_row=header_row + 1),
        start=header_row + 1,
    ):
        zebra = row_index % 2 == 0
        for cell in row:
            cell.font = Font(
                name="Arial",
                size=10.5,
                color=theme.text,
            )
            cell.alignment = Alignment(
                vertical="top",
                horizontal="left",
                wrap_text=True,
            )
            cell.border = Border(
                bottom=Side(style="hair", color=theme.border),
            )
            if zebra:
                cell.fill = PatternFill("solid", fgColor=theme.zebra)

        ws.row_dimensions[row_index].height = 24


def _auto_width(
    ws,
    min_row=4,
    min_width=14,
    max_width=42,
):
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        width = min_width

        for row in range(min_row, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            if cell.value is None:
                continue

            text = str(cell.value)
            longest_line = max(
                (len(part) for part in text.splitlines()),
                default=0,
            )
            width = max(
                width,
                min(longest_line + 3, max_width),
            )

        ws.column_dimensions[letter].width = width


def _finish_table(ws, theme, header_row=4):
    _style_table(ws, theme, header_row=header_row)
    _auto_width(ws, min_row=header_row)

    if ws.max_column and ws.max_row >= header_row:
        end = get_column_letter(ws.max_column)
        ws.auto_filter.ref = f"A{header_row}:{end}{ws.max_row}"
        ws.print_area = f"A1:{end}{ws.max_row}"


def create_conversation_excel(
    messages,
    title="Local AI Conversation",
    output_dir=OUTPUT_DIR,
    model_name="",
    preset="Red Executive Workbook",
):
    theme = get_theme(preset)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "classic" if theme.family == "classic" else "red"
    path = output_dir / (
        f"local_ai_{prefix}_workbook_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".xlsx"
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Conversation"

    _style_sheet(
        ws,
        title,
        theme,
        columns=3,
        model_name=model_name,
        source_label="Current conversation",
    )
    ws.append([])
    ws.append(["Role", "Content", "Artifact path"])

    for message in messages:
        role = message.get("role", "")
        if role == "system":
            continue

        ws.append([
            role.upper(),
            message.get("content", ""),
            message.get("path", "") if role == "artifact" else "",
        ])

    _finish_table(ws, theme)
    wb.save(path)
    return path


def create_structured_excel(
    model_output,
    title="Local AI Workbook",
    output_dir=OUTPUT_DIR,
    source_text="",
    model_name="",
    preset="Red Executive Workbook",
):
    theme = get_theme(preset)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "classic" if theme.family == "classic" else "red"
    path = output_dir / (
        f"local_ai_{prefix}_workbook_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".xlsx"
    )

    try:
        payload = _clean_json(model_output)
    except Exception:
        payload = {
            "title": title,
            "sheets": [{
                "name": "Content",
                "headers": ["Content"],
                "rows": [[model_output]],
            }],
        }

    payload = sanitize_structured_payload(
        payload,
        source_text=source_text,
    )

    workbook_title = str(payload.get("title") or title)
    sheets = payload.get("sheets") or []
    if not sheets:
        sheets = [{
            "name": "Content",
            "headers": ["Content"],
            "rows": [["No data"]],
        }]

    wb = Workbook()
    wb.remove(wb.active)

    for index, spec in enumerate(sheets):
        name = _safe_sheet_name(
            spec.get("name")
            or f"Sheet {index + 1}"
        )
        ws = wb.create_sheet(name)

        headers = list(
            spec.get("headers")
            or ["Value"]
        )
        rows = spec.get("rows") or []

        _style_sheet(
            ws,
            workbook_title,
            theme,
            columns=len(headers),
            model_name=model_name,
            source_label="Custom topic",
        )

        ws.append([])
        ws.append(headers)

        for row in rows:
            if isinstance(row, list):
                ws.append(row)
            else:
                ws.append([row])

        _finish_table(ws, theme)

    wb.save(path)
    return path
