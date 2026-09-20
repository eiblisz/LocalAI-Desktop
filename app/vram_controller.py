from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox, QPushButton

from .vram_release import release_ollama_vram


class VramController:
    """Explicit FREE VRAM UI/action owner for MainWindow."""

    def __init__(self, window):
        self.window = window

    def ensure_button(self):
        window = self.window
        if getattr(window, "vram_release_button", None) is not None:
            return window.vram_release_button

        button = QPushButton("FREE VRAM")
        button.setObjectName("subtleButton")
        button.setToolTip(
            "Unload currently loaded Ollama model(s) from GPU memory. "
            "Use this before starting a VRAM-heavy image model."
        )
        button.setMaximumWidth(105)
        button.setFixedHeight(34)
        button.clicked.connect(window._release_vram)
        window.vram_release_button = button

        parent = window.resource_label.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            index = layout.indexOf(window.resource_label)
            layout.insertWidget(index + 1, button)
        return button

    def release(self):
        window = self.window
        if (
            getattr(window, "worker", None) is not None
            or getattr(window, "pdf_worker", None) is not None
            or getattr(window, "scheduled_worker", None) is not None
        ):
            QMessageBox.warning(
                window,
                "VRAM is in use",
                "Stop the active chat, document generation or scheduled task "
                "before releasing Ollama VRAM.",
            )
            return

        fallback_model = window.model_combo.currentText().strip()
        if fallback_model.startswith("No Ollama"):
            fallback_model = ""

        window.vram_release_button.setEnabled(False)
        window.vram_release_button.setText("FREEING...")
        try:
            released = release_ollama_vram(
                window.client,
                fallback_model=fallback_model,
            )
        except Exception as exc:
            QMessageBox.critical(window, "VRAM release error", str(exc))
            window.status.setText("VRAM release failed")
            window.status.setToolTip(str(exc))
        else:
            if released:
                window.status.setText("VRAM released")
                window.status.setToolTip(
                    "Unloaded Ollama model(s): " + ", ".join(released)
                )
            else:
                window.status.setText("VRAM already free")
                window.status.setToolTip(
                    "No loaded Ollama models were reported by /api/ps."
                )
            window._refresh_resources()
            QTimer.singleShot(750, window._refresh_resources)
            QTimer.singleShot(1800, window._refresh_resources)
        finally:
            window.vram_release_button.setText("FREE VRAM")
            window.vram_release_button.setEnabled(True)
