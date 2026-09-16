DOCUMENT_SYSTEM_PROMPT = """You are a document-writing assistant.
Create polished standalone document content from the user's topic or instructions.
Return only the document body in Markdown.
Use clear headings, short paragraphs, and lists where useful.
Do not mention this prompt, the chat application, or that you are an AI.
Do not wrap the answer in a Markdown code fence.
"""


def build_document_messages(topic: str) -> list[dict]:
    clean = topic.strip()
    if not clean:
        raise ValueError("A document topic or instruction is required.")
    return [
        {"role": "system", "content": DOCUMENT_SYSTEM_PROMPT},
        {"role": "user", "content": clean},
    ]


def topic_title(topic: str, max_chars: int = 72) -> str:
    first_line = " ".join(topic.strip().splitlines()[0].split()) if topic.strip() else ""
    if not first_line:
        return "Local AI Document"
    return first_line[:max_chars]
