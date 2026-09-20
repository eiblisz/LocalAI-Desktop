"""Canonical LocalAI Desktop UI theme tokens.

Keep visual values centralized here so the Desktop shell, sidebar patches and
dialogs do not drift through duplicated inline QSS literals.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    window_bg: str = "#101419"
    panel_bg: str = "#141A20"
    panel_hover: str = "#1D2630"
    panel_pressed: str = "#27323E"
    panel_disabled_border: str = "#25303A"
    input_bg: str = "#171D24"
    text_area_bg: str = "#161C23"
    chat_bg: str = "#0F1318"
    menu_bg: str = "#1B222A"
    button_bg: str = "#202730"
    button_hover: str = "#29323D"
    selection_bg: str = "#2A3440"
    splitter: str = "#252D36"
    border: str = "#2D3742"
    border_strong: str = "#35414D"
    border_input: str = "#35404C"
    button_border: str = "#323C48"
    text: str = "#EEF1F5"
    text_bright: str = "#FFFFFF"
    text_title: str = "#F4F6F8"
    text_muted: str = "#9099A6"
    text_side: str = "#AAB2BD"
    text_disabled: str = "#6F7884"
    text_status_disabled: str = "#7F8995"
    accent: str = "#C73B49"
    accent_border: str = "#D85662"
    accent_hover: str = "#D24A57"
    status_error_pulse: str = "#E07A82"
    status_error: str = "#B95A63"
    status_running_pulse: str = "#8AC89C"
    status_running: str = "#5FAE78"
    status_enabled_pulse: str = "#86C69A"
    status_enabled: str = "#65A97A"


COLORS = ThemeColors()

SIDE_MENU_HEIGHT = 34
SIDE_MENU_MIN_HEIGHT = 32
SIDE_MENU_RADIUS = 10


def side_menu_button_style():
    c = COLORS
    return (
        "QPushButton {"
        f"background:{c.panel_bg};"
        f"border:1px solid {c.border};"
        f"border-radius:{SIDE_MENU_RADIUS}px;"
        "padding:5px 10px;"
        f"color:{c.text_side};"
        "font-weight:600;"
        f"min-height:{SIDE_MENU_MIN_HEIGHT}px;"
        f"max-height:{SIDE_MENU_HEIGHT}px;"
        "}"
        "QPushButton:hover {"
        f"background:{c.panel_hover};"
        f"border-color:{c.border_strong};"
        f"color:{c.text_bright};"
        "}"
        "QPushButton:pressed {"
        f"background:{c.panel_pressed};"
        f"color:{c.text_bright};"
        "}"
    )


def muted_label_style(*, font_size=None):
    suffix = f"font-size:{int(font_size)}px;" if font_size else ""
    return f"color:{COLORS.text_muted};{suffix}"


def schedule_status_color(state, *, pulse=False):
    state = str(state or "").strip().lower()
    if state == "failed":
        return COLORS.status_error_pulse if pulse else COLORS.status_error
    if state == "running":
        return COLORS.status_running_pulse if pulse else COLORS.status_running
    if state == "enabled":
        return COLORS.status_enabled_pulse if pulse else COLORS.status_enabled
    return COLORS.text_status_disabled


def main_stylesheet():
    c = COLORS
    return f"""
QMainWindow, QWidget {{
    background: {c.window_bg};
    color: {c.text};
    font-family: "Segoe UI";
    font-size: 14px;
}}
QFrame#topbar, QFrame#sidebar, QFrame#tools {{
    background: {c.panel_bg};
}}
QLabel#brand {{
    font-size: 19px;
    font-weight: 700;
}}
QLabel#chatTitle {{
    font-size: 19px;
    font-weight: 700;
    color: {c.text_title};
}}
QLabel#muted {{
    color: {c.text_muted};
    font-size: 12px;
}}
QPushButton {{
    background: {c.button_bg};
    border: 1px solid {c.button_border};
    border-radius: 10px;
    padding: 9px 13px;
    color: {c.text_title};
}}
QPushButton:hover {{
    background: {c.button_hover};
}}
QPushButton#primary {{
    background: {c.accent};
    border: 1px solid {c.accent_border};
    font-weight: 700;
}}
QPushButton#primary:hover {{
    background: {c.accent_hover};
}}
QPushButton#sideMenuButton {{
    background: {c.panel_bg};
    border: 1px solid {c.border};
    border-radius: {SIDE_MENU_RADIUS}px;
    min-height: {SIDE_MENU_MIN_HEIGHT}px;
    max-height: {SIDE_MENU_HEIGHT}px;
    padding: 5px 10px;
    color: {c.text_side};
    font-weight: 600;
}}
QPushButton#sideMenuButton:hover {{
    background: {c.panel_hover};
    border-color: {c.border_strong};
    color: {c.text_bright};
}}
QPushButton#sideMenuButton:pressed {{
    background: {c.panel_pressed};
    color: {c.text_bright};
}}
QPushButton#sideMenuButton:disabled {{
    background: {c.panel_bg};
    border-color: {c.panel_disabled_border};
    color: {c.text_disabled};
}}
QPushButton#toolButton {{
    min-height: {SIDE_MENU_MIN_HEIGHT}px;
    max-height: {SIDE_MENU_HEIGHT}px;
    padding: 5px 10px;
    font-weight: 700;
}}
QPushButton#subtleButton {{
    background: transparent;
    border: 1px solid {c.border};
    color: {c.text_side};
}}
QListWidget#sideChatList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}
QListWidget#sideChatList::item {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {SIDE_MENU_RADIUS}px;
    color: {c.text_side};
    padding: 7px 10px;
    margin: 2px 1px;
}}
QListWidget#sideChatList::item:hover {{
    background: {c.panel_hover};
    border-color: {c.border_strong};
    color: {c.text_bright};
}}
QListWidget#sideChatList::item:selected,
QListWidget#sideChatList::item:selected:active,
QListWidget#sideChatList::item:selected:!active {{
    background: {c.panel_pressed};
    border-color: {c.border_strong};
    color: {c.text_bright};
}}
QComboBox {{
    background: {c.input_bg};
    border: 1px solid {c.border_input};
    border-radius: 9px;
    padding: 8px 12px;
    min-width: 220px;
}}
QComboBox QAbstractItemView {{
    background: {c.input_bg};
    selection-background-color: {c.selection_bg};
}}
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    background: transparent;
    color: {c.text};
    border-radius: 9px;
    padding: 11px;
    margin: 2px 0;
}}
QListWidget::item:hover {{
    background: {c.panel_hover};
    color: {c.text_bright};
}}
QListWidget::item:selected,
QListWidget::item:selected:active,
QListWidget::item:selected:!active {{
    background: {c.panel_pressed};
    color: {c.text_bright};
}}
QTextBrowser {{
    background: {c.chat_bg};
    border: none;
    padding: 18px;
    font-size: 16px;
}}
QTextEdit {{
    background: {c.text_area_bg};
    border: 1px solid {c.border_input};
    border-radius: 12px;
    padding: 10px;
    font-size: 14px;
}}
QSplitter::handle {{
    background: {c.splitter};
    width: 1px;
}}
QMenu {{
    background: {c.menu_bg};
    color: {c.text};
    border: 1px solid {c.border_input};
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 22px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background: {c.selection_bg};
}}
"""


MAIN_STYLESHEET = main_stylesheet()
SIDE_MENU_BUTTON_STYLE = side_menu_button_style()
