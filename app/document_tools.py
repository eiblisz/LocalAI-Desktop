DOCUMENT_SYSTEM_PROMPT = """You are a document-writing assistant.
Create polished standalone document content from the user's topic or instructions.
Return only the document body in Markdown.
Use clear headings, short paragraphs, and lists where useful.
Do not mention this prompt, the chat application, or that you are an AI.
Do not wrap the answer in a Markdown code fence.
"""

EXCEL_SYSTEM_PROMPT = """You are a spreadsheet planning assistant.
Return ONLY valid JSON with this exact structure:
{
  "title": "Workbook title",
  "sheets": [
    {
      "name": "Sheet name",
      "headers": ["Column A", "Column B"],
      "rows": [
        ["value 1", "value 2"]
      ]
    }
  ]
}
Create useful structured tabular data from the user's request.
Use multiple sheets when that materially improves clarity.
Do not return Markdown, explanations, or code fences.
"""

SUMMARY_SYSTEM_PROMPT = """You are a concise summarization assistant.
Return only the summary in Markdown.
Preserve the important facts, decisions, caveats, numbers and action items.
Use headings or bullets when useful.
Do not mention this prompt or that you are an AI.
"""


def build_document_messages(topic: str) -> list[dict]:
    clean = topic.strip()
    if not clean:
        raise ValueError("A document topic or instruction is required.")
    return [
        {"role": "system", "content": DOCUMENT_SYSTEM_PROMPT},
        {"role": "user", "content": clean},
    ]


def build_excel_messages(topic: str) -> list[dict]:
    clean = topic.strip()
    if not clean:
        raise ValueError("A spreadsheet topic or instruction is required.")
    return [
        {"role": "system", "content": EXCEL_SYSTEM_PROMPT},
        {"role": "user", "content": clean},
    ]


def build_summary_messages(source_text: str) -> list[dict]:
    clean = source_text.strip()
    if not clean:
        raise ValueError("Summary source content is required.")
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": clean},
    ]


def conversation_text(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        role = message.get("role", "").lower()
        if role not in {"user", "assistant"}:
            continue
        parts.append(
            f"{role.upper()}:\n{message.get('content', '').strip()}"
        )
    return "\n\n".join(parts)


def topic_title(topic: str, max_chars: int = 72) -> str:
    first_line = (
        " ".join(topic.strip().splitlines()[0].split())
        if topic.strip()
        else ""
    )
    if not first_line:
        return "Local AI Document"
    return first_line[:max_chars]
