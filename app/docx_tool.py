import re
from datetime import datetime

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .artifact_themes import get_theme
from .config import OUTPUT_DIR
from .localization import is_hungarian, labels_for_text


def _visible_messages(messages):
    return [
        m for m in messages
        if m.get("role", "").lower() not in {"system", "artifact"}
    ]


def _document_text(messages):
    visible = _visible_messages(messages)
    if len(visible) == 1:
        return visible[0].get("content", "")
    chunks = []
    for m in visible:
        chunks.append(
            f"## {m.get('role', 'assistant').upper()}\n{m.get('content', '')}"
        )
    return "\n\n".join(chunks)


def _extract_title(text, fallback):
    for line in text.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()[:100]
    return (fallback or "Local AI Document")[:100]


def _strip_first_h1(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*#\s+.+$", line):
            return "\n".join(lines[:i] + lines[i + 1:]).lstrip()
    return text


def _shade_cell(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _set_cell_border(cell, color, size="4"):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_borders = tc_pr.first_child_found_in("w:tcBorders")
    if tc_borders is None:
        tc_borders = OxmlElement("w:tcBorders")
        tc_pr.append(tc_borders)

    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = tc_borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            tc_borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def _add_inline_runs(
    paragraph,
    text,
    size,
    color,
    force_bold=False,
):
    parts = re.split(r"(\*\*.+?\*\*)", text)
    for part in parts:
        if not part:
            continue
        inline_bold = part.startswith("**") and part.endswith("**")
        clean = part[2:-2] if inline_bold else part
        run = paragraph.add_run(clean)
        run.bold = force_bold or inline_bold
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(color)


def _set_cell_text(
    cell,
    text,
    theme,
    bold=False,
    color=None,
    size=10.5,
    align=WD_ALIGN_PARAGRAPH.CENTER,
):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    _add_inline_runs(
        p,
        text,
        size=size,
        color=color or theme.text,
        force_bold=bold,
    )
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _is_table_separator(line):
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells
    )


def _parse_table_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _add_word_table(document, rows, theme):
    if not rows:
        return

    columns = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=columns)
    table.autofit = True

    for row_index, row in enumerate(rows):
        for col_index in range(columns):
            cell = table.cell(row_index, col_index)
            value = row[col_index] if col_index < len(row) else ""
            _set_cell_border(cell, theme.border)

            if row_index == 0:
                _shade_cell(cell, theme.accent_light)
                _set_cell_text(
                    cell,
                    value,
                    theme,
                    bold=True,
                    color=theme.accent_dark,
                    size=10.5 if theme.executive else 10,
                    align=WD_ALIGN_PARAGRAPH.LEFT,
                )
            else:
                if row_index % 2 == 0:
                    _shade_cell(cell, theme.zebra)
                _set_cell_text(
                    cell,
                    value,
                    theme,
                    bold=False,
                    color=theme.text,
                    size=10.5 if theme.executive else 10,
                    align=WD_ALIGN_PARAGRAPH.LEFT,
                )

    document.add_paragraph("")


def _add_markdown(document, text, theme):
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            document.add_paragraph("")
            i += 1
            continue

        if (
            "|" in line
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            rows = [_parse_table_row(line)]
            i += 2
            while i < len(lines):
                candidate = lines[i].strip()
                if not candidate or "|" not in candidate:
                    break
                rows.append(_parse_table_row(candidate))
                i += 1
            _add_word_table(document, rows, theme)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = min(len(heading.group(1)), 3)
            p = document.add_paragraph()
            run = p.add_run(heading.group(2))
            run.bold = True
            run.font.name = "Arial"
            run.font.size = Pt(
                {1: 18, 2: 15, 3: 13}[level]
                + (1 if theme.executive else 0)
            )
            run.font.color.rgb = RGBColor.from_string(
                theme.accent_dark
                if level == 1
                else theme.accent
                if level == 2
                else theme.text
            )
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.space_before = Pt(8)
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        numbered = re.match(r"^(\d+)\.\s+(.+)$", line)
        if bullet or numbered:
            text_value = bullet.group(1) if bullet else numbered.group(2)
            style = "List Bullet" if bullet else "List Number"
            p = document.add_paragraph(style=style)
            p.paragraph_format.space_after = Pt(3)
            _add_inline_runs(
                p,
                text_value,
                size=12 if theme.executive else 11.5,
                color=theme.text,
            )
            i += 1
            continue

        p = document.add_paragraph()
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.25
        _add_inline_runs(
            p,
            line,
            size=12 if theme.executive else 11.5,
            color=theme.text,
        )
        i += 1


def _base_document():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(11.5)
    return doc


def _set_footer(doc, labels, preset, theme, model_name=""):
    model = model_name.strip() or "Local model"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    for section in doc.sections:
        footer = section.footer
        p = footer.paragraphs[0]
        p.clear()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        text = (
            f'{labels["generated_footer"]}: {timestamp}'
            f" · Modell: {model}"
            f" · {preset}"
        )
        run = p.add_run(text)
        run.font.name = "Arial"
        run.font.size = Pt(7.5)
        run.font.color.rgb = RGBColor.from_string(theme.muted)


def _classic_hero_labels(text):
    if is_hungarian(text):
        return (
            "CLASSIC EXECUTIVE RIPORT",
            "Elegáns, nyomtatásbarát helyi dokumentum",
        )
    return (
        "CLASSIC EXECUTIVE REPORT",
        "Elegant print-friendly local document",
    )


def create_docx(
    messages,
    title="Local AI Report",
    output_dir=OUTPUT_DIR,
    model_name="",
    preset="Red Professional",
):
    theme = get_theme(preset)
    output_dir.mkdir(parents=True, exist_ok=True)

    family = "classic" if theme.family == "classic" else "red"
    variant = "executive" if theme.executive else "professional"
    path = output_dir / (
        f"local_ai_{family}_{variant}_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".docx"
    )

    text = _document_text(messages)
    labels = labels_for_text(text)
    document_title = _extract_title(text, title)
    body_text = _strip_first_h1(text)
    doc = _base_document()

    if not theme.executive:
        if theme.family == "red":
            table = doc.add_table(rows=1, cols=1)
            cell = table.cell(0, 0)
            _shade_cell(cell, theme.accent)
            _set_cell_border(cell, theme.accent)
            _set_cell_text(
                cell,
                document_title,
                theme,
                bold=True,
                color=theme.hero_foreground,
                size=18,
                align=WD_ALIGN_PARAGRAPH.LEFT,
            )
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(document_title)
            run.bold = True
            run.font.name = "Arial"
            run.font.size = Pt(22)
            run.font.color.rgb = RGBColor.from_string(theme.text)

            rule = doc.add_table(rows=1, cols=1)
            cell = rule.cell(0, 0)
            _shade_cell(cell, theme.accent_light)
            _set_cell_border(cell, theme.accent, size="6")
            _set_cell_text(
                cell,
                "Classic Professional",
                theme,
                color=theme.muted,
                size=9,
                align=WD_ALIGN_PARAGRAPH.LEFT,
            )

        doc.add_paragraph("")
        _add_markdown(
            doc,
            body_text or "No document content.",
            theme,
        )
        _set_footer(
            doc,
            labels,
            theme.label,
            theme,
            model_name=model_name,
        )
        doc.save(path)
        return path

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(document_title)
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor.from_string(theme.text)

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(
        "Local AI · " + labels["subtitle_executive"]
    )
    r2.font.name = "Arial"
    r2.font.size = Pt(13)
    r2.font.color.rgb = RGBColor.from_string(theme.muted)

    if theme.family == "red":
        hero_title = labels["hero_title"]
        hero_subtitle = labels["hero_subtitle"]
        hero_bg = theme.accent_dark
        hero_title_color = theme.hero_foreground
        hero_sub_color = theme.hero_subtle
    else:
        hero_title, hero_subtitle = _classic_hero_labels(text)
        hero_bg = theme.surface
        hero_title_color = theme.accent_dark
        hero_sub_color = theme.muted

    hero = doc.add_table(rows=2, cols=1)
    for cell in (hero.cell(0, 0), hero.cell(1, 0)):
        _shade_cell(cell, hero_bg)
        _set_cell_border(cell, theme.border)

    _set_cell_text(
        hero.cell(0, 0),
        hero_title,
        theme,
        bold=True,
        color=hero_title_color,
        size=17,
    )
    _set_cell_text(
        hero.cell(1, 0),
        hero_subtitle,
        theme,
        color=hero_sub_color,
        size=11.5,
    )

    doc.add_paragraph("")
    info = doc.add_table(rows=1, cols=3)
    for cell in info.rows[0].cells:
        _shade_cell(cell, theme.surface)
        _set_cell_border(cell, theme.border)

    _set_cell_text(
        info.cell(0, 0),
        labels["preset"] + "\n" + theme.label,
        theme,
        bold=True,
        size=10.5,
    )
    _set_cell_text(
        info.cell(0, 1),
        labels["execution"] + "\n" + labels["local"],
        theme,
        bold=True,
        size=10.5,
    )
    _set_cell_text(
        info.cell(0, 2),
        labels["generated"]
        + "\n"
        + datetime.now().strftime("%Y-%m-%d"),
        theme,
        bold=True,
        size=10.5,
    )

    doc.add_paragraph("")
    summary = doc.add_table(rows=1, cols=1)
    _shade_cell(summary.cell(0, 0), theme.accent_light)
    _set_cell_border(summary.cell(0, 0), theme.border)
    _set_cell_text(
        summary.cell(0, 0),
        labels["executive_summary"]
        + "\n"
        + labels["summary_text"],
        theme,
        bold=True,
        color=theme.text,
        size=11.5,
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )

    doc.add_paragraph("")
    _add_markdown(
        doc,
        body_text or "No document content.",
        theme,
    )
    _set_footer(
        doc,
        labels,
        theme.label,
        theme,
        model_name=model_name,
    )

    doc.save(path)
    return path


def create_red_professional_docx(
    messages,
    title="Local AI Report",
    output_dir=OUTPUT_DIR,
    model_name="",
):
    return create_docx(
        messages,
        title=title,
        output_dir=output_dir,
        model_name=model_name,
        preset="Red Professional",
    )


def create_red_executive_docx(
    messages,
    title="Local AI Executive Report",
    output_dir=OUTPUT_DIR,
    model_name="",
):
    return create_docx(
        messages,
        title=title,
        output_dir=output_dir,
        model_name=model_name,
        preset="Red Executive",
    )
