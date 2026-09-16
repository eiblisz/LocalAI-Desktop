from app.artifact_themes import (
    document_preset_labels,
    get_theme,
    workbook_preset_labels,
)


def test_document_theme_family_contains_classic_presets():
    labels = document_preset_labels()
    assert "Classic Professional" in labels
    assert "Classic Executive" in labels
    assert "Red Professional" in labels
    assert "Red Executive" in labels


def test_workbook_theme_family_contains_classic():
    labels = workbook_preset_labels()
    assert labels == ["Red Executive Workbook", "Classic Workbook"]


def test_classic_theme_is_not_red_palette():
    classic = get_theme("Classic Executive")
    red = get_theme("Red Executive")

    assert classic.family == "classic"
    assert classic.print_friendly is True
    assert classic.accent != red.accent
    assert classic.accent_dark != red.accent_dark
