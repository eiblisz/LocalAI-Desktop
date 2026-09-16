import html
import re
from datetime import datetime

import markdown

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
    for index, line in enumerate(lines):
        if re.match(r"^\s*#\s+.+$", line):
            return "\n".join(lines[:index] + lines[index + 1:]).lstrip()
    return text


def _body_html(text):
    return markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )


def create_html(
    messages,
    title="Local AI Report",
    preset="Red Professional",
    output_dir=OUTPUT_DIR,
):
    theme = get_theme(preset)
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = (
        "local_ai_classic"
        if theme.family == "classic"
        else "local_ai_red"
    )
    variant = "executive" if theme.executive else "professional"
    path = output_dir / f"{prefix}_{variant}_{stamp}.html"

    text = _document_text(messages)
    document_title = _extract_title(text, title)
    labels = labels_for_text(text)
    language = "hu" if is_hungarian(text) else "en"
    text = _strip_first_h1(text)
    body = _body_html(text or "No document content.")

    if theme.executive:
        if theme.family == "red":
            hero_title = labels["hero_title"]
            hero_subtitle = labels["hero_subtitle"]
        else:
            hero_title = (
                "CLASSIC EXECUTIVE RIPORT"
                if language == "hu"
                else "CLASSIC EXECUTIVE REPORT"
            )
            hero_subtitle = (
                "Elegáns, nyomtatásbarát helyi dokumentum"
                if language == "hu"
                else "Elegant print-friendly local document"
            )

        hero = (
            '<section class="hero">'
            '<div class="hero-title">' + html.escape(hero_title) + '</div>'
            '<div class="hero-sub">' + html.escape(hero_subtitle) + '</div>'
            '</section>'
            '<section class="cards">'
            '<div><b>' + html.escape(labels["preset"]) + '</b><span>'
            + html.escape(theme.label) + '</span></div>'
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

    css = f"""
    :root {{
      --accent:#{theme.accent};
      --accent-dark:#{theme.accent_dark};
      --accent-light:#{theme.accent_light};
      --text:#{theme.text};
      --muted:#{theme.muted};
      --surface:#{theme.surface};
      --border:#{theme.border};
      --zebra:#{theme.zebra};
      --hero-fg:#{theme.hero_foreground};
      --hero-subtle:#{theme.hero_subtle};
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      background:#f2f3f5;
      color:var(--text);
      font-family:Arial,Segoe UI,sans-serif;
      font-size:18px;
      line-height:1.62;
    }}
    .page {{
      max-width:980px;
      margin:36px auto;
      background:white;
      padding:56px 68px 70px;
      box-shadow:0 10px 40px rgba(0,0,0,.10);
    }}
    h1 {{ font-size:34px; margin:0 0 12px; color:var(--text); }}
    h2 {{ font-size:25px; color:var(--accent); margin-top:38px; }}
    h3 {{ font-size:21px; color:var(--text); margin-top:28px; }}
    p, li {{ font-size:18px; }}
    table {{
      width:100%;
      border-collapse:collapse;
      margin:24px 0;
      font-size:16px;
    }}
    th {{
      background:var(--accent-light);
      color:var(--accent-dark);
    }}
    td, th {{
      border:1px solid var(--border);
      padding:12px 14px;
      text-align:left;
      vertical-align:top;
    }}
    tbody tr:nth-child(even) {{ background:var(--zebra); }}
    code, pre {{ font-family:Consolas,monospace; }}
    pre {{
      background:#151d24;
      color:#eef1f5;
      padding:18px;
      border-radius:8px;
      overflow:auto;
    }}
    .subtitle {{
      text-align:center;
      color:var(--muted);
      margin-bottom:26px;
      font-size:18px;
    }}
    .hero {{
      background:var(--accent-dark);
      color:var(--hero-fg);
      padding:28px;
      text-align:center;
      border-radius:4px;
      margin:28px 0;
    }}
    .hero.simple {{ background:var(--accent); }}
    .hero-title {{ font-size:26px; font-weight:700; }}
    .hero-sub {{ margin-top:10px; color:var(--hero-subtle); }}
    .cards {{
      display:grid;
      grid-template-columns:repeat(3,1fr);
      gap:1px;
      background:var(--border);
      margin:26px 0;
      border:1px solid var(--border);
    }}
    .cards div {{
      background:var(--surface);
      padding:20px;
      text-align:center;
    }}
    .cards b,.cards span {{ display:block; }}
    .cards span {{ margin-top:8px; }}
    .summary {{
      background:var(--accent-light);
      border-left:5px solid var(--accent);
      padding:18px 22px;
      margin:28px 0;
    }}
    .footer {{
      margin-top:48px;
      padding-top:16px;
      border-top:1px solid var(--border);
      color:var(--muted);
      font-size:13px;
      display:flex;
      justify-content:space-between;
    }}
    @media print {{
      body {{ background:white; }}
      .page {{
        box-shadow:none;
        margin:0;
        max-width:none;
        padding:20mm 18mm 18mm;
      }}
    }}
    """

    subtitle = (
        labels["subtitle_executive"]
        if theme.executive
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
<div class="subtitle">Local AI · {html.escape(subtitle)}</div>
{hero}
<article>{body}</article>
<footer class="footer">
<span>{html.escape(labels["generated_footer"])} {datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
<span>{html.escape(theme.label)}</span>
</footer>
</main>
</body>
</html>"""

    path.write_text(html_doc, encoding="utf-8")
    return path


def create_red_html(
    messages,
    title="Local AI Report",
    executive=False,
    output_dir=OUTPUT_DIR,
):
    preset = "Red Executive" if executive else "Red Professional"
    return create_html(
        messages,
        title=title,
        preset=preset,
        output_dir=output_dir,
    )
