import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton

from app.ui_theme import (
    COLORS,
    MAIN_STYLESHEET,
    SIDE_MENU_BUTTON_STYLE,
    muted_label_style,
    schedule_status_color,
)


def _app():
    return QApplication.instance() or QApplication([])


def _render_center_color(button):
    app = _app()
    button.resize(160, 40)
    button.show()
    button.ensurePolished()
    app.processEvents()

    image = QImage(
        button.size(),
        QImage.Format.Format_ARGB32,
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    button.render(painter)
    painter.end()

    color = image.pixelColor(
        button.width() // 2,
        button.height() // 2,
    )
    button.hide()
    return color.name().upper()


def test_canonical_theme_preserves_accepted_sidebar_visual_tokens():
    assert COLORS.panel_bg == "#141A20"
    assert COLORS.panel_hover == "#1D2630"
    assert COLORS.panel_pressed == "#27323E"
    assert COLORS.text_side == "#AAB2BD"
    assert COLORS.text_bright == "#FFFFFF"

    assert f"background:{COLORS.panel_bg};" in SIDE_MENU_BUTTON_STYLE
    assert f"background:{COLORS.panel_hover};" in SIDE_MENU_BUTTON_STYLE
    assert f"background:{COLORS.panel_pressed};" in SIDE_MENU_BUTTON_STYLE


def test_rendered_side_menu_button_uses_canonical_panel_background():
    button = QPushButton("")
    button.setObjectName("sideMenuButton")
    button.setStyleSheet(MAIN_STYLESHEET)

    assert _render_center_color(button) == COLORS.panel_bg.upper()


def test_rendered_primary_button_uses_canonical_accent_background():
    button = QPushButton("")
    button.setObjectName("primary")
    button.setStyleSheet(MAIN_STYLESHEET)

    assert _render_center_color(button) == COLORS.accent.upper()


def test_schedule_status_colors_are_centralized_and_stable():
    assert schedule_status_color("failed", pulse=True) == COLORS.status_error_pulse
    assert schedule_status_color("failed") == COLORS.status_error
    assert schedule_status_color("running", pulse=True) == COLORS.status_running_pulse
    assert schedule_status_color("running") == COLORS.status_running
    assert schedule_status_color("enabled", pulse=True) == COLORS.status_enabled_pulse
    assert schedule_status_color("enabled") == COLORS.status_enabled
    assert schedule_status_color("disabled") == COLORS.text_status_disabled


def test_muted_label_style_uses_canonical_muted_text():
    assert muted_label_style() == f"color:{COLORS.text_muted};"
    assert muted_label_style(font_size=12) == (
        f"color:{COLORS.text_muted};font-size:12px;"
    )
