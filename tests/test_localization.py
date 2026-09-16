from app.localization import is_hungarian, labels_for_text


def test_hungarian_detection_and_labels():
    text = "Készíts egy magyar összehasonlító táblázatot a helyi modellekről."
    assert is_hungarian(text) is True
    labels = labels_for_text(text)
    assert labels["executive_summary"] == "Vezetői összefoglaló"
    assert labels["generated"] == "Készült"


def test_english_labels_remain_english():
    text = "Create a technical report comparing local coding models."
    assert is_hungarian(text) is False
    labels = labels_for_text(text)
    assert labels["executive_summary"] == "Executive Summary"
    assert labels["generated"] == "Generated"
