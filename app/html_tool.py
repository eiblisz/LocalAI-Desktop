import html
import re
from datetime import datetime

import markdown

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
    for index, line in enumerate(lines):
        if re.match(r"^\s*#\s+.+$", line):
            return "\n".join(lines[:index] + lines[index + 1:]).lstrip()
    return text


def _body_html(text):
    return markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )


def create_red_html(
    messages,
    title="Local AI Report",
    executive=False,
    output_dir=OUTPUT_DIR,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = "local_ai_executive" if executive else "local_ai_report"
    path = output_dir / f"{name}_{stamp}.html"

    text = _document_text(messages)
    document_title = _extract_title(text, title)
    labels = labels_for_text(text)
    language = "hu" if is_hungarian(text) else "en"
    text = _strip_first_h1(text)
    body = _body_html(text or "No document content.")

    if executive:
        hero = (
            '<section class="hero">'
            '<div class="hero-title">' + html.escape(labels["hero_title"]) + '</div>'
            '<div class="hero-sub">' + html.escape(labels["hero_subtitle"]) + '</div>'
            '</section>'
            '<section class="cards">'
            '<div><b>' + html.escape(labels["preset"]) + '</b><span>Red Executive</span></div>'
            '<div><b>' + html.escape(labels["execution"]) + '</b><span>'
            + html.escape(labels["local"]) + '</span></div>'
            '<div><b>' + html.escape(labels["generated"]) + '</b><span>'
            + datetime.now().strftime("%Y-%m-%d")
            + '</span></div>'
            '</section>'
            '<section class="summary">'
            '<b>' + html.escape(labels["executive_summary"]) + '</b>'
            '<p>' + html.escape(labels["summary_text"]) + '</p>'
            '</section>'
        )
    else:
        hero = (
            '<section class="hero simple"><div class="hero-title">'
            + html.escape(document_title)
            + '</div></section>'
        )

    css = """
    :root { --red:#B92F3B; --darkred:#8E1F2D; --text:#1F2630;
            --muted:#6C737F; --light:#F9EDEF; }
    * { box-sizing:border-box; }
    body { margin:0; background:#f2f3f5; color:var(--text);
           font-family:Arial,Segoe UI,sans-serif; font-size:18px;
           line-height:1.62; }
    .page { max-width:980px; margin:36px auto; background:white;
            padding:56px 68px 70px; box-shadow:0 10px 40px rgba(0,0,0,.10); }
    h1 { font-size:34px; margin:0 0 12px; color:var(--text); }
    h2 { font-size:25px; color:var(--red); margin-top:38px; }
    h3 { font-size:21px; color:var(--text); margin-top:28px; }
    p, li { font-size:18px; }
    table { width:100%; border-collapse:collapse; margin:24px 0;
            font-size:16px; }
    th { background:var(--light); color:var(--darkred); }
    td, th { border:1px solid #d9dee5; padding:12px 14px;
             text-align:left; vertical-align:top; }
    code, pre { font-family:Consolas,monospace; }
    pre { background:#151d24; color:#eef1f5; padding:18px;
          border-radius:10px; overflow:auto; }
    .subtitle { text-align:center; color:var(--muted);
                margin-bottom:26px; font-size:18px; }
    .hero { background:var(--darkred); color:white; padding:28px;
            text-align:center; border-radius:4px; margin:28px 0; }
    .hero.simple { background:var(--red); }
    .hero-title { font-size:26px; font-weight:700; }
    .hero-sub { margin-top:10px; color:#ffe9ec; }
    .cards { display:grid; grid-template-columns:repeat(3,1fr); gap:1px;
             background:#d9dee5; margin:26px 0; border:1px solid #d9dee5; }
    .cards div { background:#f4f6f8; padding:20px; text-align:center; }
    .cards b,.cards span { display:block; }
    .cards span { margin-top:8px; }
    .summary { background:var(--light); border-left:5px solid var(--red);
               padding:18px 22px; margin:28px 0; }
    .footer { margin-top:48px; padding-top:16px; border-top:1px solid #e1e4e8;
              color:var(--muted); font-size:14px; display:flex;
              justify-content:space-between; }
    @media print {
      body { background:white; }
      .page { box-shadow:none; margin:0; max-width:none; }
    }
    """

    preset = "Red Executive" if executive else "Red Professional"
    subtitle = (
        labels["subtitle_executive"]
        if executive
        else labels["subtitle_professional"]
    )

    html_doc = f"""<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(document_title)}</title>
<style>{css}</style>
</head>
<body>
<main class="page">
<h1>{html.escape(document_title)}</h1>
<div class="subtitle">Local AI · {subtitle}</div>
{hero}
<article>{body}</article>
<footer class="footer">
<span>{html.escape(labels["generated_footer"])} {datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
<span>{preset}</span>
</footer>
</main>
</body>
</html>"""

    path.write_text(html_doc, encoding="utf-8")
    return path
