from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QMessageBox, QPushButton

from .ollama_process_control import (
    kill_ollama,
    kill_ollama_model_processes,
    restart_ollama,
)
from .vram_release import release_ollama_vram


ACTION_FREE_VRAM = "FREE VRAM"
ACTION_KILL_MODEL = "KILL MODEL PROCESS"
ACTION_RESTART_OLLAMA = "RESTART OLLAMA"
ACTION_KILL_OLLAMA = "KILL OLLAMA"


class VramController:
    """Explicit Ollama/VRAM control owner for MainWindow."""

    def __init__(self, window):
        self.window = window

    def ensure_controls(self):
        window = self.window
        if getattr(window, "ollama_action_combo", None) is not None:
            return window.ollama_action_combo

        combo = QComboBox()
        combo.setObjectName("ollamaActionCombo")
        combo.addItems(
            [
                ACTION_FREE_VRAM,
                ACTION_KILL_MODEL,
                ACTION_RESTART_OLLAMA,
                ACTION_KILL_OLLAMA,
            ]
        )
        combo.setCurrentText(ACTION_FREE_VRAM)
        combo.setFixedHeight(34)
        combo.setMinimumWidth(155)
        combo.setMaximumWidth(175)
        combo.setToolTip(
            "Ollama controls: release VRAM normally, force-stop a stuck model "
            "runner, restart Ollama, or force-stop Ollama completely."
        )

        button = QPushButton("RUN")
        button.setObjectName("subtleButton")
        button.setFixedHeight(34)
        button.setMaximumWidth(58)
        button.setToolTip("Run the selected Ollama control action.")
        button.clicked.connect(self.run_selected_action)

        window.ollama_action_combo = combo
        window.ollama_action_button = button
        # Compatibility alias for older source/tests that referenced the button.
        window.vram_release_button = button

        parent = window.resource_label.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            index = layout.indexOf(window.resource_label)
            layout.insertWidget(index + 1, combo)
            layout.insertWidget(index + 2, button)
        return combo

    def _active_jobs(self):
        window = self.window
        return [
            worker
            for worker in (
                getattr(window, "worker", None),
                getattr(window, "pdf_worker", None),
                getattr(window, "scheduled_worker", None),
            )
            if worker is not None
        ]

    def _request_stop_active_jobs(self):
        for worker in self._active_jobs():
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        if getattr(self.window, "stop_button", None) is not None:
            self.window.stop_button.setEnabled(False)
        stop_thinking = getattr(self.window, "_stop_thinking_indicator", None)
        if callable(stop_thinking):
            stop_thinking()

    def run_selected_action(self):
        window = self.window
        action = window.ollama_action_combo.currentText().strip()

        if action == ACTION_FREE_VRAM:
            self.release()
            return
        if action == ACTION_KILL_MODEL:
            self.kill_model_process()
            return
        if action == ACTION_RESTART_OLLAMA:
            self.restart()
            return
        if action == ACTION_KILL_OLLAMA:
            self.kill_server()
            return

        QMessageBox.warning(
            window,
            "Ollama control",
            f"Unknown Ollama action: {action}",
        )

    def release(self):
        window = self.window
        if self._active_jobs():
            QMessageBox.warning(
                window,
                "VRAM is in use",
                "Stop the active chat, document generation or scheduled task "
                "before releasing Ollama VRAM. If the model is stuck, choose "
                "KILL MODEL PROCESS instead.",
            )
            return

        fallback_model = window.model_combo.currentText().strip()
        if fallback_model.startswith("No Ollama"):
            fallback_model = ""

        window.ollama_action_button.setEnabled(False)
        window.status.setText("Releasing Ollama VRAM...")
        try:
            released = release_ollama_vram(
                window.client,
                fallback_model=fallback_model,
                timeout=4.0,
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
            window.ollama_action_button.setEnabled(True)

    def kill_model_process(self):
        window = self.window
        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Stopping Ollama model process...")
        try:
            pids = kill_ollama_model_processes()
        except Exception as exc:
            QMessageBox.critical(window, "Kill model process error", str(exc))
            window.status.setText("Model process kill failed")
            window.status.setToolTip(str(exc))
        else:
            if pids:
                window.status.setText(
                    "Stopped Ollama model process: "
                    + ", ".join(str(pid) for pid in pids)
                )
            else:
                window.status.setText("No Ollama model process was running")
            window.status.setToolTip("")
            QTimer.singleShot(500, window._refresh_resources)
            QTimer.singleShot(900, window._refresh_desktop)
        finally:
            window.ollama_action_button.setEnabled(True)

    def kill_server(self):
        window = self.window
        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Stopping Ollama...")
        try:
            pids = kill_ollama()
        except Exception as exc:
            QMessageBox.critical(window, "Kill Ollama error", str(exc))
            window.status.setText("Ollama kill failed")
            window.status.setToolTip(str(exc))
        else:
            window.status.setText(
                "Ollama stopped"
                + (
                    ": " + ", ".join(str(pid) for pid in pids)
                    if pids
                    else ""
                )
            )
            window.status.setToolTip("")
            QTimer.singleShot(500, window._refresh_resources)
        finally:
            window.ollama_action_button.setEnabled(True)

    def restart(self):
        window = self.window
        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Restarting Ollama...")
        try:
            result = restart_ollama()
        except Exception as exc:
            QMessageBox.critical(window, "Restart Ollama error", str(exc))
            window.status.setText("Ollama restart failed")
            window.status.setToolTip(str(exc))
        else:
            pid = result.get("started_pid")
            window.status.setText(
                f"Ollama restarted (PID {pid})" if pid else "Ollama restarted"
            )
            window.status.setToolTip("")
            QTimer.singleShot(1200, window._refresh_desktop)
            QTimer.singleShot(2200, window._refresh_desktop)
        finally:
            window.ollama_action_button.setEnabled(True)
