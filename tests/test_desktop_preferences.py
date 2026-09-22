from app.desktop_preferences import DEFAULT_WEB_MODE, DesktopPreferences


def test_web_mode_defaults_to_on_without_a_persisted_selection(tmp_path):
    preferences = DesktopPreferences(tmp_path)

    assert preferences.web_mode() == DEFAULT_WEB_MODE == "ON"


def test_explicit_web_mode_is_preserved_across_preferences_instances(tmp_path):
    preferences = DesktopPreferences(tmp_path)

    assert preferences.set_web_mode("OFF") == "OFF"
    assert DesktopPreferences(tmp_path).web_mode() == "OFF"
