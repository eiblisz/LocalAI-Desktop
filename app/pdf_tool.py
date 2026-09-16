from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer

from .config import OUTPUT_DIR

HEADER_RED = colors.HexColor("#B92F3B")
TEXT_DARK = colors.HexColor("#20242A")
MUTED = colors.HexColor("#6C737F")


def _register_font() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                pdfmetrics.registerFont(TTFont("LocalAIUnicode", str(candidate)))
                return "LocalAIUnicode"
            except Exception:
                pass
    return "Helvetica"


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def create_red_professional_pdf(
    messages: list[dict],
    title: str = "Local AI Report",
    output_dir: Path = OUTPUT_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"local_ai_report_{timestamp}.pdf"

    font_name = _register_font()
    page_width, page_height = A4

    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=34 * mm,
        bottomMargin=18 * mm,
        title=title,
    )

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")

    def draw_page(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(HEADER_RED)
        canvas.rect(0, page_height - 25 * mm, page_width, 25 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(font_name, 15)
        canvas.drawString(18 * mm, page_height - 15 * mm, title[:72])
        canvas.setFillColor(MUTED)
        canvas.setFont(font_name, 8.5)
        canvas.drawString(18 * mm, 10 * mm, datetime.now().strftime("Generated %Y-%m-%d %H:%M"))
        canvas.drawRightString(page_width - 18 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="red", frames=[frame], onPage=draw_page)])

    styles = getSampleStyleSheet()
    role_style = ParagraphStyle(
        "Role", parent=styles["Heading3"], fontName=font_name, fontSize=9,
        leading=11, textColor=HEADER_RED, spaceAfter=3 * mm
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName=font_name, fontSize=10,
        leading=14, textColor=TEXT_DARK, alignment=TA_LEFT, spaceAfter=6 * mm
    )
    intro_style = ParagraphStyle(
        "Intro", parent=styles["BodyText"], fontName=font_name, fontSize=9,
        leading=12, textColor=MUTED, spaceAfter=8 * mm
    )

    story = [
        Paragraph(_escape("Conversation export - Red Professional preset"), intro_style),
        Spacer(1, 2 * mm),
    ]

    for message in messages:
        role = message.get("role", "assistant").upper()
        content = message.get("content", "")
        if role == "SYSTEM":
            continue
        story.append(Paragraph(_escape(role), role_style))
        story.append(Paragraph(_escape(content), body_style))

    if not any(m.get("role") != "system" for m in messages):
        story.append(Paragraph("No conversation content.", body_style))

    doc.build(story)
    return path
