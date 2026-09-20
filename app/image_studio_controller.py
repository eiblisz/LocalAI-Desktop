import os
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QMessageBox, QPushButton

COMFYUI_URL = "http://127.0.0.1:8188/"
DEFAULT_COMFYUI_LAUNCHER = Path(
    r"C:\ComicNewsAI\comfyui\ComfyUI_windows_portable\run_nvidia_gpu.bat"
)


def comfyui_ready(url=COMFYUI_URL, timeout=1.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def launcher_path():
    configured = os.environ.get("LOCALAI_COMFYUI_LAUNCHER", "").strip()
    return Path(configured) if configured else DEFAULT_COMFYUI_LAUNCHER


def launch_comfyui(path):
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(
        ["cmd.exe", "/c", "start", "", str(path)],
        cwd=str(path.parent),
        creationflags=creationflags,
    )


def wait_for_comfyui(timeout=90.0, interval=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if comfyui_ready():
            return True
        time.sleep(interval)
    return False


class ImageStudioController:
    """Explicit ComfyUI/Image Studio controller."""

    def __init__(self, window):
        self.window = window

    def show_embedded(self):
        window = self.window
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWidgets import QMainWindow

            image_window = getattr(window, "image_studio_window", None)
            if image_window is None:
                image_window = QMainWindow(window)
                image_window.setWindowTitle("LocalAI - Image Studio")
                image_window.resize(1500, 920)
                view = QWebEngineView(image_window)
                view.setUrl(QUrl(COMFYUI_URL))
                image_window.setCentralWidget(view)
                image_window.image_studio_web_view = view
                window.image_studio_window = image_window
            else:
                view = getattr(image_window, "image_studio_web_view", None)
                if view is not None:
                    view.setUrl(QUrl(COMFYUI_URL))
            image_window.show()
            image_window.raise_()
            image_window.activateWindow()
            window.status.setText("Image Studio: embedded ComfyUI ready")
            window.status.setToolTip("")
            return True
        except Exception as exc:
            QMessageBox.information(
                window,
                "Image Studio",
                "The embedded web view is unavailable, so ComfyUI will open "
                "in the system browser.\n\n" + str(exc),
            )
            webbrowser.open(COMFYUI_URL)
            window.status.setText("Image Studio: browser fallback")
            window.status.setToolTip(str(exc))
            return False

    def open(self):
        window = self.window
        if comfyui_ready():
            self.show_embedded()
            return

        if (
            getattr(window, "worker", None) is not None
            or getattr(window, "pdf_worker", None) is not None
            or getattr(window, "scheduled_worker", None) is not None
        ):
            QMessageBox.warning(
                window,
                "Image Studio",
                "LocalAI is busy. Stop the active generation before starting ComfyUI.",
            )
            return

        launcher = launcher_path()
        if not launcher.is_file():
            QMessageBox.critical(
                window,
                "Image Studio",
                f"ComfyUI launcher not found:\n{launcher}\n\n"
                "Set LOCALAI_COMFYUI_LAUNCHER to override it.",
            )
            window.status.setText("Image Studio: launcher not found")
            return

        try:
            window._release_vram()
            launch_comfyui(launcher)
        except Exception as exc:
            QMessageBox.critical(window, "Image Studio", str(exc))
            window.status.setText("Image Studio: launch failed")
            window.status.setToolTip(str(exc))
            return

        window.status.setText("Image Studio: starting ComfyUI...")
        QTimer.singleShot(1000, window._poll_comfyui_ready)

    def poll_ready(self, remaining=90):
        window = self.window
        if comfyui_ready():
            self.show_embedded()
            return
        if remaining <= 0:
            window.status.setText("Image Studio: ComfyUI startup timeout")
            window.status.setToolTip(
                "ComfyUI did not become ready at 127.0.0.1:8188 within 90 seconds."
            )
            QMessageBox.warning(
                window,
                "Image Studio",
                "ComfyUI was started but did not become ready within 90 seconds.",
            )
            return
        QTimer.singleShot(
            1000,
            lambda: window._poll_comfyui_ready(remaining - 1),
        )

    def install_tool_button(self, layout):
        window = self.window
        if layout is None or "IMAGE" in window.tool_buttons:
            return None
        button = QPushButton("IMAGE")
        button.setObjectName("sideMenuButton")
        button.setFixedHeight(34)
        button.setStyleSheet(window.SIDE_MENU_BUTTON_INLINE_STYLE if hasattr(window, "SIDE_MENU_BUTTON_INLINE_STYLE") else "")
        button.setToolTip(
            "Open Image Studio powered by the local ComfyUI service."
        )
        button.clicked.connect(window._open_image_studio)
        window.tool_buttons["IMAGE"] = button
        layout.insertWidget(1, button)
        return button
