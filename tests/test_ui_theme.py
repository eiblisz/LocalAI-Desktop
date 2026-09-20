import os
import subprocess
import sys
import textwrap

from app.ui_theme import (
    COLORS,
    SIDE_MENU_BUTTON_STYLE,
    muted_label_style,
    schedule_status_color,
)


def test_canonical_theme_preserves_accepted_sidebar_visual_tokens():
    assert COLORS.panel_bg == "#141A20"
    assert COLORS.panel_hover == "#1D2630"
    assert COLORS.panel_pressed == "#27323E"
    assert COLORS.text_side == "#AAB2BD"
    assert COLORS.text_bright == "#FFFFFF"

    assert f"background:{COLORS.panel_bg};" in SIDE_MENU_BUTTON_STYLE
    assert f"background:{COLORS.panel_hover};" in SIDE_MENU_BUTTON_STYLE
    assert f"background:{COLORS.panel_pressed};" in SIDE_MENU_BUTTON_STYLE


def test_rendered_buttons_match_canonical_theme_in_isolated_qt_process():
    script = textwrap.dedent(
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication, QPushButton

        from app.ui_theme import COLORS, MAIN_STYLESHEET

        app = QApplication([])

        def rendered_center(object_name):
            button = QPushButton("")
            button.setObjectName(object_name)
            button.setStyleSheet(MAIN_STYLESHEET)
            button.resize(160, 40)
            button.show()
            button.ensurePolished()
            app.processEvents()

            image = QImage(
                button.size(),
                QImage.Format.Format_ARGB32,
            )
            image.fill(Qt.GlobalColor.transparent)
            button.render(image)
            color = image.pixelColor(
                button.width() // 2,
                button.height() // 2,
            ).name().upper()
            button.close()
            button.deleteLater()
            app.processEvents()
            return color

        assert rendered_center("sideMenuButton") == COLORS.panel_bg.upper()
        assert rendered_center("primary") == COLORS.accent.upper()

        app.quit()
        """
    )

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "minimal"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        "isolated Qt render check failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


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
