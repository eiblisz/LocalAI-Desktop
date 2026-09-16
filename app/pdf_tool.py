import html
import re
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .config import OUTPUT_DIR

HEADER_RED = colors.HexColor("#B92F3B")
DARK_RED = colors.HexColor("#8E1F2D")
LIGHT_RED = colors.HexColor("#F9EDEF")
TEXT_DARK = colors.HexColor("#1F2630")
MUTED = colors.HexColor("#6C737F")
LIGHT_GREY = colors.HexColor("#F4F6F8")
MID_GREY = colors.HexColor("#D9DEE5")


def _register_font_family() -> str:
    candidates = {
        "regular": Path(r"C:\Windows\Fonts\arial.ttf"),
        "bold": Path(r"C:\Windows\Fonts\arialbd.ttf"),
        "italic": Path(r"C:\Windows\Fonts\ariali.ttf"),
        "bold_italic": Path(r"C:\Windows\Fonts\arialbi.ttf"),
    }

    if all(path.exists() for path in candidates.values()):
        try:
            pdfmetrics.registerFont(TTFont("LocalAI", str(candidates["regular"])))
            pdfmetrics.registerFont(TTFont("LocalAI-Bold", str(candidates["bold"])))
            pdfmetrics.registerFont(TTFont("LocalAI-Italic", str(candidates["italic"])))
            pdfmetrics.registerFont(
                TTFont("LocalAI-BoldItalic", str(candidates["bold_italic"]))
            )
            pdfmetrics.registerFontFamily(
                "LocalAI",
                normal="LocalAI",
                bold="LocalAI-Bold",
                italic="LocalAI-Italic",
                boldItalic="LocalAI-BoldItalic",
            )
            return "LocalAI"
        except Exception:
            pass

    return "Helvetica"


def markdown_to_reportlab(text: str) -> str:
    rendered_lines = []
    for raw_line in text.splitlines():
        line = html.escape(raw_line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(
            r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
            r"<i>\1</i>",
            line,
        )
        rendered_lines.append(line)
    return "<br/>".join(rendered_lines)


def _visible_messages(messages: list[dict]) -> list[dict]:
    return [
        message
        for message in messages
        if message.get("role", "").lower() not in {"system", "artifact"}
    ]


def _document_text(messages: list[dict]) -> str:
    visible = _visible_messages(messages)
    if not visible:
        return ""

    if len(visible) == 1:
        return visible[0].get("content", "")

    chunks = []
    for message in visible:
        role = message.get("role", "assistant").upper()
        chunks.append(f"## {role}\n{message.get('content', '')}")
    return "\n\n".join(chunks)


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()[:100]
    return fallback.strip()[:100] or "Local AI Document"


def _strip_first_h1(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\s*#\s+.+$", line):
            return "\n".join(lines[:index] + lines[index + 1 :]).lstrip()
    return text


def _make_styles(font_name: str, executive: bool = False) -> dict:
    styles = getSampleStyleSheet()
    body_size = 12.0 if executive else 11.5
    body_leading = 17 if executive else 16

    return {
        "body": ParagraphStyle(
            "LocalAIBodyExecutive" if executive else "LocalAIBody",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=body_size,
            leading=body_leading,
            textColor=TEXT_DARK,
            alignment=TA_LEFT,
            spaceAfter=4 * mm,
        ),
        "h1": ParagraphStyle(
            "LocalAIH1Executive" if executive else "LocalAIH1",
            parent=styles["Heading1"],
            fontName=font_name,
            fontSize=19 if executive else 17,
            leading=24 if executive else 21,
            textColor=DARK_RED,
            spaceBefore=5 * mm,
            spaceAfter=4 * mm,
        ),
        "h2": ParagraphStyle(
            "LocalAIH2Executive" if executive else "LocalAIH2",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=16 if executive else 14.5,
            leading=20 if executive else 18,
            textColor=HEADER_RED,
            spaceBefore=4 * mm,
            spaceAfter=3 * mm,
        ),
        "h3": ParagraphStyle(
            "LocalAIH3Executive" if executive else "LocalAIH3",
            parent=styles["Heading3"],
            fontName=font_name,
            fontSize=13.5 if executive else 12.5,
            leading=17,
            textColor=TEXT_DARK,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "small": ParagraphStyle(
            "LocalAISmallExecutive" if executive else "LocalAISmall",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=9.5,
            leading=12,
            textColor=MUTED,
        ),
        "center_title": ParagraphStyle(
            "LocalAICenterTitle",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=26,
            leading=31,
            alignment=TA_CENTER,
            textColor=TEXT_DARK,
            spaceAfter=4 * mm,
        ),
        "center_subtitle": ParagraphStyle(
            "LocalAICenterSubtitle",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=13.5,
            leading=17,
            alignment=TA_CENTER,
            textColor=MUTED,
            spaceAfter=6 * mm,
        ),
    }


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(
        re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells
    )


def _markdown_flowables(
    text: str,
    styles: dict,
    available_width: float,
    accent=HEADER_RED,
    enable_progress: bool = False,
) -> list:
    flowables = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        if not stripped:
            flowables.append(Spacer(1, 2.2 * mm))
            i += 1
            continue

        if (
            "|" in stripped
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            table_rows = [
                [cell.strip() for cell in stripped.strip("|").split("|")]
            ]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                table_rows.append(
                    [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                )
                i += 1

            cell_style = ParagraphStyle(
                "LocalAITableCell",
                parent=styles["body"],
                fontSize=max(styles["body"].fontSize - 1.2, 9.5),
                leading=max(styles["body"].leading - 2, 12),
                spaceAfter=0,
            )
            data = [
                [Paragraph(markdown_to_reportlab(cell), cell_style) for cell in row]
                for row in table_rows
            ]
            columns = max(len(row) for row in data)
            widths = [available_width / columns] * columns
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_RED),
                        ("TEXTCOLOR", (0, 0), (-1, 0), DARK_RED),
                        ("FONTNAME", (0, 0), (-1, 0), styles["body"].fontName),
                        ("GRID", (0, 0), (-1, -1), 0.4, MID_GREY),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                )
            )
            flowables.extend([table, Spacer(1, 5 * mm)])
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                style = styles["h1"]
            elif level == 2:
                style = styles["h2"]
            else:
                style = styles["h3"]
            flowables.append(
                Paragraph(markdown_to_reportlab(heading.group(2)), style)
            )
            i += 1
            continue

        metric = re.match(r"^(.+?):\s*(\d{1,3})%\s*$", stripped)
        if enable_progress and metric:
            value = max(0, min(100, int(metric.group(2))))
            label = Paragraph(
                f"<b>{html.escape(metric.group(1).strip())}</b>: {value}%",
                styles["body"],
            )
            filled = available_width * value / 100
            empty = available_width - filled
            bar = Table(
                [["", ""]],
                colWidths=[max(filled, 0.1), max(empty, 0.1)],
                rowHeights=[5.5 * mm],
            )
            bar.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, 0), accent),
                        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#ECEFF2")),
                        ("BOX", (0, 0), (-1, -1), 0, colors.white),
                    ]
                )
            )
            flowables.extend([label, bar, Spacer(1, 3.5 * mm)])
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if bullet:
            flowables.append(
                Paragraph(
                    f"• {markdown_to_reportlab(bullet.group(1))}",
                    styles["body"],
                )
            )
            i += 1
            continue

        if numbered:
            flowables.append(
                Paragraph(
                    f"<b>{numbered.group(1)}.</b> "
                    f"{markdown_to_reportlab(numbered.group(2))}",
                    styles["body"],
                )
            )
            i += 1
            continue

        flowables.append(Paragraph(markdown_to_reportlab(stripped), styles["body"]))
        i += 1

    return flowables


def _footer(canvas, page_width: float, font_name: str, label: str) -> None:
    canvas.setFillColor(MUTED)
    canvas.setFont(font_name, 9)
    canvas.drawString(
        18 * mm,
        10 * mm,
        datetime.now().strftime("Generated %Y-%m-%d %H:%M"),
    )
    canvas.drawCentredString(page_width / 2, 10 * mm, label)
    canvas.drawRightString(
        page_width - 18 * mm,
        10 * mm,
        f"Page {canvas.getPageNumber()}",
    )


def create_red_professional_pdf(
    messages: list[dict],
    title: str = "Local AI Report",
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"local_ai_report_{timestamp}.pdf"

    font_name = _register_font_family()
    page_width, page_height = A4
    text = _document_text(messages)
    document_title = _extract_title(text, title)
    text = _strip_first_h1(text)
    styles = _make_styles(font_name, executive=False)

    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=36 * mm,
        bottomMargin=18 * mm,
        title=document_title,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")

    def draw_page(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(HEADER_RED)
        canvas.rect(
            0, page_height - 27 * mm, page_width, 27 * mm, fill=1, stroke=0
        )
        canvas.setFillColor(colors.white)
        canvas.setFont(font_name, 18)
        canvas.drawString(
            18 * mm, page_height - 16.5 * mm, document_title[:78]
        )
        _footer(canvas, page_width, font_name, "Red Professional")
        canvas.restoreState()

    doc.addPageTemplates(
        [PageTemplate(id="red", frames=[frame], onPage=draw_page)]
    )
    story = _markdown_flowables(
        text or "No document content.",
        styles,
        doc.width,
        accent=HEADER_RED,
        enable_progress=False,
    )
    doc.build(story)
    return path


def create_red_executive_pdf(
    messages: list[dict],
    title: str = "Local AI Executive Report",
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"local_ai_executive_{timestamp}.pdf"

    font_name = _register_font_family()
    page_width, page_height = A4
    text = _document_text(messages)
    document_title = _extract_title(text, title)
    text = _strip_first_h1(text)
    styles = _make_styles(font_name, executive=True)

    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=document_title,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")

    def draw_page(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(HEADER_RED)
        canvas.setLineWidth(2.0)
        canvas.line(
            20 * mm,
            page_height - 12 * mm,
            page_width - 20 * mm,
            page_height - 12 * mm,
        )
        _footer(canvas, page_width, font_name, "Red Executive")
        canvas.restoreState()

    doc.addPageTemplates(
        [PageTemplate(id="redExecutive", frames=[frame], onPage=draw_page)]
    )

    hero_title = Paragraph(document_title, styles["center_title"])
    hero_subtitle = Paragraph(
        "Local AI · Executive / Technical Report",
        styles["center_subtitle"],
    )

    hero_main_style = ParagraphStyle(
        "HeroMain",
        parent=styles["center_subtitle"],
        fontName=font_name,
        fontSize=17,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.white,
        spaceAfter=0,
    )
    hero_sub_style = ParagraphStyle(
        "HeroSub",
        parent=styles["center_subtitle"],
        fontName=font_name,
        fontSize=11.5,
        leading=15,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#FFE9EC"),
        spaceAfter=0,
    )
    hero = Table(
        [
            [Paragraph("<b>RED EXECUTIVE REPORT</b>", hero_main_style)],
            [Paragraph("Structured local-model document output", hero_sub_style)],
        ],
        colWidths=[doc.width],
        rowHeights=[14 * mm, 11 * mm],
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DARK_RED),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0, DARK_RED),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    info_style = ParagraphStyle(
        "InfoCard",
        parent=styles["small"],
        fontName=font_name,
        fontSize=10.5,
        leading=14,
        alignment=TA_CENTER,
        textColor=TEXT_DARK,
    )
    info = Table(
        [[
            Paragraph("<b>Preset</b><br/>Red Executive", info_style),
            Paragraph("<b>Execution</b><br/>Local", info_style),
            Paragraph(
                f"<b>Generated</b><br/>{datetime.now().strftime('%Y-%m-%d')}",
                info_style,
            ),
        ]],
        colWidths=[doc.width / 3.0] * 3,
        rowHeights=[22 * mm],
        hAlign="CENTER",
    )
    info.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREY),
                ("BOX", (0, 0), (-1, -1), 0.5, MID_GREY),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    summary_style = ParagraphStyle(
        "ExecutiveSummary",
        parent=styles["body"],
        fontName=font_name,
        fontSize=11.5,
        leading=16,
        textColor=TEXT_DARK,
        spaceAfter=0,
    )
    summary_box = Table(
        [[Paragraph(
            "<b>Executive Summary</b><br/>"
            "This report was generated locally using the selected AI model. "
            "The document below preserves the model's structured content while "
            "applying the Red Executive visual system.",
            summary_style,
        )]],
        colWidths=[doc.width],
    )
    summary_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_RED),
                ("LINEBEFORE", (0, 0), (0, -1), 4, HEADER_RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    story = [
        Spacer(1, 10 * mm),
        hero_title,
        hero_subtitle,
        Spacer(1, 3 * mm),
        hero,
        Spacer(1, 8 * mm),
        info,
        Spacer(1, 8 * mm),
        summary_box,
        Spacer(1, 7 * mm),
    ]
    story.extend(
        _markdown_flowables(
            text or "No document content.",
            styles,
            doc.width,
            accent=HEADER_RED,
            enable_progress=True,
        )
    )

    doc.build(story)
    return path
