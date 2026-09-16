HU_MARKERS = {
    " a ", " az ", " és ", " hogy ", " egy ", " vagy ", " nem ", " helyi ",
    " magyar ", " készíts ", " összehasonlító ", " táblázat ", " előny ",
    " hátrány ", " eredmény ", " modell ", " adatok ", " fejezet ",
}


def is_hungarian(text: str) -> bool:
    sample = f" {text.lower()} "
    accented = sum(sample.count(ch) for ch in "áéíóöőúüű")
    marker_hits = sum(1 for marker in HU_MARKERS if marker in sample)
    return accented >= 2 or marker_hits >= 3


def labels_for_text(text: str) -> dict:
    if is_hungarian(text):
        return {
            "subtitle_executive": "Vezetői / Technikai Riport",
            "subtitle_professional": "Professzionális Riport",
            "hero_title": "RED EXECUTIVE RIPORT",
            "hero_subtitle": "Strukturált helyi modell által készített dokumentum",
            "preset": "Sablon",
            "execution": "Futtatás",
            "local": "Helyi",
            "generated": "Készült",
            "executive_summary": "Vezetői összefoglaló",
            "summary_text": (
                "Ez a dokumentum helyben, a kiválasztott AI-modellel készült. "
                "Az alábbi tartalom a modell strukturált kimenetét őrzi meg "
                "a Red Executive vizuális rendszerben."
            ),
            "page": "Oldal",
            "generated_footer": "Készült",
        }

    return {
        "subtitle_executive": "Executive / Technical Report",
        "subtitle_professional": "Professional Report",
        "hero_title": "RED EXECUTIVE REPORT",
        "hero_subtitle": "Structured local-model document output",
        "preset": "Preset",
        "execution": "Execution",
        "local": "Local",
        "generated": "Generated",
        "executive_summary": "Executive Summary",
        "summary_text": (
            "This document was generated locally using the selected AI model. "
            "The content below preserves the model's structured output while "
            "applying the Red Executive visual system."
        ),
        "page": "Page",
        "generated_footer": "Generated",
    }
