from .vram_release import release_ollama_vram


def install_vram_release_patch(main_window_module):
    window_class = main_window_module.MainWindow
    if getattr(window_class, "_vram_release_patch_installed", False):
        return

    original_build_ui = window_class._build_ui

    def _release_vram(self):
        if (
            getattr(self, "worker", None) is not None
            or getattr(self, "pdf_worker", None) is not None
            or getattr(self, "scheduled_worker", None) is not None
        ):
            main_window_module.QMessageBox.warning(
                self,
                "VRAM is in use",
                "Stop the active chat, document generation or scheduled task before releasing Ollama VRAM.",
            )
            return

        fallback_model = self.model_combo.currentText().strip()
        if fallback_model.startswith("No Ollama"):
            fallback_model = ""

        self.vram_release_button.setEnabled(False)
        self.vram_release_button.setText("FREEING...")
        try:
            released = release_ollama_vram(
                self.client,
                fallback_model=fallback_model,
            )
        except Exception as exc:
            main_window_module.QMessageBox.critical(
                self,
                "VRAM release error",
                str(exc),
            )
            self.status.setText("VRAM release failed")
            self.status.setToolTip(str(exc))
        else:
            if released:
                self.status.setText("VRAM released")
                self.status.setToolTip(
                    "Unloaded Ollama model(s): " + ", ".join(released)
                )
            else:
                self.status.setText("VRAM already free")
                self.status.setToolTip("No loaded Ollama models were reported by /api/ps.")
            self._refresh_resources()
            main_window_module.QTimer.singleShot(750, self._refresh_resources)
            main_window_module.QTimer.singleShot(1800, self._refresh_resources)
        finally:
            self.vram_release_button.setText("FREE VRAM")
            self.vram_release_button.setEnabled(True)

    def _build_ui(self):
        original_build_ui(self)

        button = main_window_module.QPushButton("FREE VRAM")
        button.setObjectName("subtleButton")
        button.setToolTip(
            "Unload currently loaded Ollama model(s) from GPU memory. "
            "Use this before starting a VRAM-heavy image model."
        )
        button.setMaximumWidth(105)
        button.clicked.connect(self._release_vram)
        self.vram_release_button = button

        parent = self.resource_label.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            index = layout.indexOf(self.resource_label)
            layout.insertWidget(index + 1, button)

    window_class._release_vram = _release_vram
    window_class._build_ui = _build_ui
    window_class._vram_release_patch_installed = True
