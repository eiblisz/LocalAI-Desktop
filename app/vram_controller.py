import os
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QMessageBox, QPushButton

from .ollama_process_control import (
    kill_ollama,
    kill_ollama_model_processes,
    list_external_ollama_consumers,
    restart_ollama,
)
from .ollama_resource_coordinator import OWNER_UNKNOWN


ACTION_FREE_VRAM = "FREE VRAM"
ACTION_KILL_MODEL = "KILL MODEL PROCESS"
ACTION_RESTART_OLLAMA = "RESTART OLLAMA"
ACTION_EMERGENCY_KILL = "EMERGENCY OLLAMA KILL"


class VramController:
    """Explicit shared-Ollama control owner for MainWindow."""

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
                ACTION_EMERGENCY_KILL,
            ]
        )
        combo.setCurrentText(ACTION_FREE_VRAM)
        combo.setFixedHeight(34)
        combo.setMinimumWidth(170)
        combo.setMaximumWidth(205)
        combo.setToolTip(
            "Shared Ollama controls. Destructive model actions require proven "
            "LocalAI Desktop ownership. Global actions always require explicit confirmation."
        )

        button = QPushButton("RUN")
        button.setObjectName("subtleButton")
        button.setFixedHeight(34)
        button.setMaximumWidth(58)
        button.setToolTip("Run the selected Ollama control action.")
        button.clicked.connect(self.run_selected_action)

        window.ollama_action_combo = combo
        window.ollama_action_button = button
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

    def _external_consumers(self):
        try:
            return list_external_ollama_consumers(
                timeout=3.0,
                exclude_pids=[os.getpid()],
            )
        except Exception:
            return None

    @staticmethod
    def _blocked_text(blocked):
        if not blocked:
            return ""
        parts = []
        for item in blocked[:4]:
            parts.append(
                "{model}: {owner}/{state}".format(
                    model=item.get("model") or "unknown model",
                    owner=item.get("owner") or OWNER_UNKNOWN,
                    state=item.get("state") or "UNKNOWN",
                )
            )
        return "; ".join(parts)

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
        if action == ACTION_EMERGENCY_KILL:
            self.emergency_kill_server()
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
                "FREE VRAM is blocked while LocalAI Desktop has an active job.",
            )
            return False

        window.ollama_action_button.setEnabled(False)
        window.status.setText("Checking Ollama ownership...")
        try:
            result = window.client.release_owned_models(timeout=5.0)
        except Exception as exc:
            QMessageBox.critical(window, "VRAM release error", str(exc))
            window.status.setText("VRAM release blocked")
            window.status.setToolTip(str(exc))
            return False
        else:
            released = list(result.get("released") or [])
            blocked = list(result.get("blocked") or [])
            reconciled = list(result.get("reconciled") or [])

            if blocked:
                detail = self._blocked_text(blocked)
                QMessageBox.warning(
                    window,
                    "Shared Ollama resource",
                    "FREE VRAM blocked because ownership is not proven for: "
                    + detail,
                )
                window.status.setText("FREE VRAM blocked: shared/unknown owner")
                window.status.setToolTip(detail)
                return False
            elif released:
                window.status.setText("VRAM released")
                window.status.setToolTip(
                    "Gracefully unloaded Desktop-owned model(s): "
                    + ", ".join(released)
                )
            elif reconciled:
                window.status.setText("Ollama runtime reconciled")
                window.status.setToolTip(
                    "Model listing was stale; no runner process existed: "
                    + ", ".join(reconciled)
                )
            else:
                window.status.setText("No Desktop-owned Ollama model to release")
                window.status.setToolTip("")
            window._refresh_resources()
            QTimer.singleShot(750, window._refresh_resources)
            QTimer.singleShot(1500, window._refresh_desktop)
            return True
        finally:
            window.ollama_action_button.setEnabled(True)

    def kill_model_process(self):
        window = self.window
        model = window.model_combo.currentText().strip()
        if not model or model.startswith("No Ollama"):
            QMessageBox.warning(
                window,
                "Kill model process",
                "No selected Ollama model has proven Desktop ownership.",
            )
            return

        foreign = window.client.foreign_active_leases()
        if foreign:
            QMessageBox.warning(
                window,
                "Shared Ollama resource",
                "KILL MODEL PROCESS blocked because another registered owner has an active lease.",
            )
            return

        external = self._external_consumers()
        if external is None:
            QMessageBox.warning(
                window,
                "Shared Ollama resource",
                "KILL MODEL PROCESS blocked because external ownership could not be verified.",
            )
            return
        if external:
            QMessageBox.warning(
                window,
                "Shared Ollama resource",
                "KILL MODEL PROCESS blocked because another local Ollama consumer is visible.",
            )
            return

        pids = window.client.owned_model_process_ids(
            model,
            allow_active=True,
        )
        if not pids:
            QMessageBox.warning(
                window,
                "Shared Ollama resource",
                "KILL MODEL PROCESS blocked: no ownership-authorized runner PID exists "
                "for the selected model.",
            )
            return

        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Stopping Desktop-owned Ollama model process...")
        try:
            killed = kill_ollama_model_processes(pids=pids)
        except Exception as exc:
            QMessageBox.critical(window, "Kill model process error", str(exc))
            window.status.setText("Model process kill failed")
            window.status.setToolTip(str(exc))
        else:
            if killed:
                window.client.resource_store.mark_stale(
                    model,
                    detail="Desktop-owned runner explicitly killed by user",
                )
                window.status.setText(
                    "Stopped Desktop-owned model process: "
                    + ", ".join(str(pid) for pid in killed)
                )
            else:
                window.status.setText("Authorized model process was already gone")
            window.status.setToolTip("")
            QTimer.singleShot(500, window._refresh_resources)
            QTimer.singleShot(900, window._refresh_desktop)
        finally:
            window.ollama_action_button.setEnabled(True)

    def restart(self):
        window = self.window
        foreign = window.client.foreign_active_leases()
        external = self._external_consumers()
        if foreign or external is None or external:
            QMessageBox.warning(
                window,
                "Shared Ollama resource",
                "RESTART OLLAMA blocked because shared-runtime ownership is active "
                "or cannot be proven safe.",
            )
            return

        answer = QMessageBox.question(
            window,
            "Restart shared Ollama runtime",
            "Mas helyi AI folyamatokat is megszakithat.\n\n"
            "Biztosan ujrainditja az Ollama szervert?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Restarting shared Ollama...")
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

    def emergency_kill_server(self):
        window = self.window
        answer = QMessageBox.question(
            window,
            "EMERGENCY OLLAMA KILL",
            "Mas helyi AI folyamatokat is megszakithat.\n\n"
            "Ez globalisan leallitja az Ollama szervert es runner folyamatait. "
            "Csak veszhelyzetben hasznalja. Folytatja?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._request_stop_active_jobs()
        window.ollama_action_button.setEnabled(False)
        window.status.setText("Emergency stopping Ollama...")
        try:
            pids = kill_ollama()
        except Exception as exc:
            QMessageBox.critical(window, "Emergency Ollama kill error", str(exc))
            window.status.setText("Emergency Ollama kill failed")
            window.status.setToolTip(str(exc))
        else:
            window.status.setText(
                "Ollama emergency stop complete"
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
