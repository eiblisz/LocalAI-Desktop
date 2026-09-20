import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from .memory_store import (
    ALLOWED_CATEGORIES,
    ALLOWED_IMPORTANCE,
    MemoryStore,
)


_ALL_STATUSES = ("active", "superseded", "archived", "deleted")


class MemoryDialog(QDialog):
    changed = Signal()

    def __init__(self, store: MemoryStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.current_id = ""

        self.setWindowTitle("Memory")
        self.resize(1180, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        title = QLabel("MEMORY")
        title.setStyleSheet("font-size:17px;font-weight:700;")
        left.addWidget(title)

        intro = QLabel(
            "Review the durable facts LocalAI may reuse in future chats. "
            "Edits create a new revision so earlier values remain auditable."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9099A6;")
        left.addWidget(intro)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search memories...")
        self.search_edit.textChanged.connect(self.refresh)
        filters.addWidget(self.search_edit, 1)

        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", "")
        for category in sorted(ALLOWED_CATEGORIES):
            self.category_filter.addItem(category, category)
        self.category_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.category_filter)

        self.status_filter = QComboBox()
        self.status_filter.addItem("Active", "active")
        self.status_filter.addItem("All history", "all")
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)
        left.addLayout(filters)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#9099A6;font-size:12px;")
        left.addWidget(self.count_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Subject",
            "Key",
            "Value",
            "Category",
            "Importance",
            "Status",
            "Updated",
        ])
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        left.addWidget(self.table, 1)

        refresh_button = QPushButton("REFRESH")
        refresh_button.clicked.connect(self.refresh)
        left.addWidget(refresh_button)

        root.addLayout(left, 3)

        right = QVBoxLayout()
        details_title = QLabel("MEMORY DETAILS")
        details_title.setStyleSheet("font-size:17px;font-weight:700;")
        right.addWidget(details_title)

        form = QFormLayout()

        self.category_combo = QComboBox()
        for category in sorted(ALLOWED_CATEGORIES):
            self.category_combo.addItem(category, category)
        form.addRow("Category", self.category_combo)

        self.scope_edit = QLineEdit()
        form.addRow("Scope", self.scope_edit)

        self.subject_edit = QLineEdit()
        form.addRow("Subject", self.subject_edit)

        self.key_edit = QLineEdit()
        form.addRow("Key", self.key_edit)

        self.value_edit = QTextEdit()
        self.value_edit.setMinimumHeight(90)
        form.addRow("Value", self.value_edit)

        self.importance_combo = QComboBox()
        for importance in [
            "IGNORE",
            "SESSION_ONLY",
            "REMEMBER",
            "IMPORTANT",
            "PINNED",
        ]:
            if importance in ALLOWED_IMPORTANCE:
                self.importance_combo.addItem(importance, importance)
        form.addRow("Importance", self.importance_combo)

        self.status_label = QLabel("No memory selected")
        self.status_label.setWordWrap(True)
        form.addRow("Status", self.status_label)

        right.addLayout(form)

        action_row = QHBoxLayout()
        self.revise_button = QPushButton("SAVE REVISION")
        self.revise_button.clicked.connect(self._revise)
        action_row.addWidget(self.revise_button)

        self.pin_button = QPushButton("PIN")
        self.pin_button.clicked.connect(self._toggle_pin)
        action_row.addWidget(self.pin_button)

        self.archive_button = QPushButton("ARCHIVE")
        self.archive_button.clicked.connect(self._archive)
        action_row.addWidget(self.archive_button)

        self.delete_button = QPushButton("DELETE")
        self.delete_button.clicked.connect(self._delete)
        action_row.addWidget(self.delete_button)
        right.addLayout(action_row)

        provenance_title = QLabel("PROVENANCE / REVISION CHAIN")
        provenance_title.setStyleSheet("font-weight:700;")
        right.addWidget(provenance_title)

        self.provenance = QTextBrowser()
        self.provenance.setOpenExternalLinks(False)
        right.addWidget(self.provenance, 1)

        note = QLabel(
            "DELETE is a soft-delete in the canonical memory store. "
            "Revisions preserve the previous record as superseded history."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7F8995;font-size:12px;")
        right.addWidget(note)

        root.addLayout(right, 2)
        self._set_editor_enabled(False)

    def refresh(self, *_args, selected_id=None):
        selected_id = selected_id or self.current_id
        statuses = (
            ("active",)
            if self.status_filter.currentData() == "active"
            else _ALL_STATUSES
        )
        category = str(self.category_filter.currentData() or "").strip()
        query = self.search_edit.text().strip().casefold()

        rows = self.store.list_memories(
            category=category or None,
            statuses=statuses,
            include_session_only=True,
        )
        if query:
            rows = [
                memory
                for memory in rows
                if query in " ".join(
                    str(memory.get(field, ""))
                    for field in (
                        "category",
                        "scope",
                        "subject",
                        "key",
                        "value",
                        "importance",
                        "status",
                    )
                ).casefold()
            ]

        self.table.setRowCount(0)
        selected_row = -1
        for row_index, memory in enumerate(rows):
            self.table.insertRow(row_index)
            values = [
                memory.get("subject", ""),
                memory.get("key", ""),
                memory.get("value", ""),
                memory.get("category", ""),
                memory.get("importance", ""),
                memory.get("status", ""),
                memory.get("updated_at", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, memory["id"])
                self.table.setItem(row_index, column, item)
            if memory["id"] == selected_id:
                selected_row = row_index

        self.count_label.setText(f"{len(rows)} memory record(s)")
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif rows:
            self.table.selectRow(0)
        else:
            self.current_id = ""
            self._clear_editor()

    def _selection_changed(self):
        selected = self.table.selectedItems()
        if not selected:
            self.current_id = ""
            self._clear_editor()
            return

        row = selected[0].row()
        item = self.table.item(row, 0)
        memory_id = str(item.data(Qt.UserRole) or "")
        if not memory_id:
            return
        self._load_memory(memory_id)

    def _load_memory(self, memory_id):
        memory = self.store.get_memory(memory_id)
        self.current_id = memory_id

        self._set_combo_data(self.category_combo, memory["category"])
        self.scope_edit.setText(memory["scope"])
        self.subject_edit.setText(memory["subject"])
        self.key_edit.setText(memory["key"])
        self.value_edit.setPlainText(memory["value"])
        self._set_combo_data(self.importance_combo, memory["importance"])

        status = memory.get("status", "")
        self.status_label.setText(
            f"{status} · confidence {float(memory.get('confidence', 0.0)):.2f} · "
            f"updated {memory.get('updated_at', '')}"
        )
        self.pin_button.setText(
            "UNPIN" if memory.get("importance") == "PINNED" else "PIN"
        )
        self._set_editor_enabled(status == "active")
        self._render_provenance(memory_id)

    def _render_provenance(self, memory_id):
        memory = self.store.get_memory(memory_id)
        sources = self.store.list_memory_sources(memory_id)
        lineage = self.store.memory_lineage(memory_id)

        parts = [
            f"<b>ID</b>: {html.escape(memory_id)}",
            f"<b>Source chat</b>: "
            f"{html.escape(str(memory.get('source_chat_id') or 'none'))}",
            "<hr><b>Sources</b>",
        ]
        if not sources:
            parts.append("<div>No provenance records.</div>")
        else:
            for source in sources:
                excerpt = html.escape(str(source.get("excerpt") or ""))
                parts.append(
                    "<div style='margin:6px 0'>"
                    f"<b>{html.escape(str(source.get('source_type') or 'source'))}</b>"
                    f" · {html.escape(str(source.get('source_ref') or ''))}<br>"
                    f"{excerpt}</div>"
                )

        parts.append("<hr><b>Revision chain</b>")
        for item in lineage:
            marker = "→" if item["id"] == memory_id else "•"
            parts.append(
                "<div style='margin:5px 0'>"
                f"{marker} <b>{html.escape(item.get('status', ''))}</b> · "
                f"{html.escape(item.get('updated_at', ''))}<br>"
                f"{html.escape(item.get('subject', ''))} / "
                f"{html.escape(item.get('key', ''))}: "
                f"{html.escape(item.get('value', ''))}<br>"
                f"<span style='color:#9099A6'>{html.escape(item['id'])}</span>"
                "</div>"
            )

        self.provenance.setHtml("".join(parts))

    @staticmethod
    def _set_combo_data(combo, value):
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_editor_enabled(self, enabled):
        for widget in (
            self.category_combo,
            self.scope_edit,
            self.subject_edit,
            self.key_edit,
            self.value_edit,
            self.importance_combo,
            self.revise_button,
            self.pin_button,
            self.archive_button,
            self.delete_button,
        ):
            widget.setEnabled(bool(enabled))

    def _clear_editor(self):
        self.scope_edit.clear()
        self.subject_edit.clear()
        self.key_edit.clear()
        self.value_edit.clear()
        self.status_label.setText("No memory selected")
        self.provenance.clear()
        self._set_editor_enabled(False)

    def _revise(self):
        if not self.current_id:
            return
        try:
            revised = self.store.revise_memory(
                self.current_id,
                category=self.category_combo.currentData(),
                scope=self.scope_edit.text(),
                subject=self.subject_edit.text(),
                key=self.key_edit.text(),
                value=self.value_edit.toPlainText(),
                importance=self.importance_combo.currentData(),
                source_type="memory_ui",
                source_ref=self.current_id,
                source_excerpt="Manual revision from Memory UI",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Memory revision error", str(exc))
            return

        self.changed.emit()
        self.current_id = revised["id"]
        self.refresh(selected_id=revised["id"])

    def _toggle_pin(self):
        if not self.current_id:
            return
        try:
            memory = self.store.get_memory(self.current_id)
            importance = (
                "IMPORTANT"
                if memory.get("importance") == "PINNED"
                else "PINNED"
            )
            updated = self.store.set_importance(
                self.current_id,
                importance,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Memory pin error", str(exc))
            return

        self.changed.emit()
        self.refresh(selected_id=updated["id"])

    def _archive(self):
        if not self.current_id:
            return
        if QMessageBox.question(
            self,
            "Archive memory",
            "Archive this memory? It will stop being used as active context.",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            memory = self.store.archive_memory(self.current_id)
        except Exception as exc:
            QMessageBox.critical(self, "Memory archive error", str(exc))
            return
        self.changed.emit()
        self.refresh(selected_id=memory["id"])

    def _delete(self):
        if not self.current_id:
            return
        if QMessageBox.question(
            self,
            "Delete memory",
            "Soft-delete this memory from active use?",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            memory = self.store.delete_memory(self.current_id)
        except Exception as exc:
            QMessageBox.critical(self, "Memory delete error", str(exc))
            return
        self.changed.emit()
        self.refresh(selected_id=memory["id"])
