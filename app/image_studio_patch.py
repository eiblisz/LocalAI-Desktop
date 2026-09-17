import os
import subprocess
import time
import urllib.request
from pathlib import Path

COMFYUI_URL = "http://127.0.0.1:8188/"
DEFAULT_COMFYUI_LAUNCHER = Path(r"C:\ComicNewsAI\comfyui\ComfyUI_windows_portable\run_nvidia_gpu.bat")


def _comfyui_ready(url=COMFYUI_URL, timeout=1.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _launcher_path():
    configured = os.environ.get("LOCALAI_COMFYUI_LAUNCHER", "").strip()
    return Path(configured) if configured else DEFAULT_COMFYUI_LAUNCHER


def _launch_comfyui(path):
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(
        ["cmd.exe", "/c", "start", "", str(path)],
        cwd=str(path.parent),
        creationflags=creationflags,
    )


def _wait_for_comfyui(timeout=90.0, interval=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _comfyui_ready():
            return True
        time.sleep(interval)
    return False


def install_image_studio_patch(main_window_module):
    window_class = main_window_module.MainWindow
    if getattr(window_class, "_image_studio_patch_installed", False):
        return

    original_build_tools_panel = window_class._build_tools_panel

    def _open_image_studio(self):
        if _comfyui_ready():
            main_window_module.webbrowser.open(COMFYUI_URL)
            self.status.setText("Image Studio: ComfyUI ready")
            return

        if (
            getattr(self, "worker", None) is not None
            or getattr(self, "pdf_worker", None) is not None
            or getattr(self, "scheduled_worker", None) is not None
        ):
            main_window_module.QMessageBox.warning(
                self,
                "Image Studio",
                "LocalAI is busy. Stop the active generation before starting ComfyUI.",
            )
            return

        launcher = _launcher_path()
        if not launcher.is_file():
            main_window_module.QMessageBox.critical(
                self,
                "Image Studio",
                f"ComfyUI launcher not found:\n{launcher}\n\nSet LOCALAI_COMFYUI_LAUNCHER to override it.",
            )
            self.status.setText("Image Studio: launcher not found")
            return

        try:
            self._release_vram()
            _launch_comfyui(launcher)
        except Exception as exc:
            main_window_module.QMessageBox.critical(self, "Image Studio", str(exc))
            self.status.setText("Image Studio: launch failed")
            self.status.setToolTip(str(exc))
            return

        self.status.setText("Image Studio: starting ComfyUI...")
        main_window_module.QTimer.singleShot(1000, self._poll_comfyui_ready)

    def _poll_comfyui_ready(self, remaining=90):
        if _comfyui_ready():
            self.status.setText("Image Studio: ComfyUI ready")
            self.status.setToolTip("")
            main_window_module.webbrowser.open(COMFYUI_URL)
            return
        if remaining <= 0:
            self.status.setText("Image Studio: ComfyUI startup timeout")
            self.status.setToolTip("ComfyUI did not become ready at 127.0.0.1:8188 within 90 seconds.")
            main_window_module.QMessageBox.warning(
                self,
                "Image Studio",
                "ComfyUI was started but did not become ready within 90 seconds.",
            )
            return
        main_window_module.QTimer.singleShot(
            1000, lambda: self._poll_comfyui_ready(remaining - 1)
        )

    def _build_tools_panel(self):
        frame = original_build_tools_panel(self)
        layout = frame.layout()
        if layout is not None and "IMAGE" not in self.tool_buttons:
            button = main_window_module.QPushButton("IMAGE")
            button.setObjectName("toolButton")
            button.setToolTip("Open Image Studio powered by the local ComfyUI service.")
            button.clicked.connect(self._open_image_studio)
            self.tool_buttons["IMAGE"] = button
            # title is index 0; IMAGE belongs before PDF.
            layout.insertWidget(1, button)
        return frame

    window_class._open_image_studio = _open_image_studio
    window_class._poll_comfyui_ready = _poll_comfyui_ready
    window_class._build_tools_panel = _build_tools_panel
    window_class._image_studio_patch_installed = True
