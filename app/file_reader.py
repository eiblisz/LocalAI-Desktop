from pathlib import Path

from docx import Document
from pypdf import PdfReader

from .config import SUPPORTED_TEXT_EXTENSIONS

MAX_ATTACHMENT_CHARS = 120_000


def _limit(text: str) -> str:
    if len(text) <= MAX_ATTACHMENT_CHARS:
        return text
    return text[:MAX_ATTACHMENT_CHARS] + "\n\n[Attachment truncated by LocalAI Desktop]"


def read_attachment(path_str: str) -> str:
    path = Path(path_str)
    suffix = path.suffix.lower()

    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return _limit(path.read_text(encoding="utf-8", errors="replace"))

    if suffix == ".pdf":
        reader = PdfReader(str(path))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append(f"\n--- PAGE {index} ---\n{page.extract_text() or ''}")
        return _limit("\n".join(pages))

    if suffix == ".docx":
        document = Document(str(path))
        return _limit("\n".join(paragraph.text for paragraph in document.paragraphs))

    raise ValueError(f"Unsupported attachment type: {suffix or '[no extension]'}")
