from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
)

from .scheduler_store import ScheduledTaskStore
from .ui_theme import muted_label_style


TASK_TYPES = {
    "weather": "Weather",
    "ebay": "eBay Search",
    "computer": "Computer Status",
    "custom": "Custom",
}
TYPE_KEYS_BY_LABEL = {label: key for key, label in TASK_TYPES.items()}


class SchedulerDialog(QDialog):
    run_requested = Signal(str)
    tasks_changed = Signal()

    def __init__(self, store: ScheduledTaskStore, models=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.models = list(models or [])
        self.current_id = ""

        self.setWindowTitle("Scheduled Tasks")
        self.resize(960, 720)
        self._build_ui()
        self.set_models(self.models)
        self._refresh_list()
        self._new_task()

    def _build_ui(self):
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        title = QLabel("SCHEDULED TASKS")
        title.setStyleSheet("font-size:17px;font-weight:700;")
        left.addWidget(title)

        self.task_list = QListWidget()
        self.task_list.itemClicked.connect(self._task_selected)
        left.addWidget(self.task_list, 1)

        new_button = QPushButton("NEW TASK")
        new_button.clicked.connect(self._new_task)
        left.addWidget(new_button)

        root.addLayout(left, 1)

        right = QVBoxLayout()
        intro = QLabel(
            "All recurring automations live here. Weather and eBay use their own "
            "bounded data sources. Custom tasks can optionally use read-only Web Search."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(muted_label_style())
        right.addWidget(intro)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Example: Hourly weather check")
        form.addRow("Task name", self.name_edit)

        self.task_type_combo = QComboBox()
        self.task_type_combo.addItems(list(TASK_TYPES.values()))
        self.task_type_combo.currentTextChanged.connect(self._task_type_changed)
        form.addRow("Task type", self.task_type_combo)

        self.model_combo = QComboBox()
        form.addRow("Model", self.model_combo)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Example: Summarize the result and tell me only if something needs attention."
        )
        self.prompt_edit.setFixedHeight(110)
        form.addRow("Prompt", self.prompt_edit)

        self.location_label = QLabel("Weather location")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Example: Bad Nenndorf, Germany")
        form.addRow(self.location_label, self.location_edit)

        self.ebay_query_label = QLabel("eBay search")
        self.ebay_query_edit = QLineEdit()
        self.ebay_query_edit.setPlaceholderText(
            "Optional - leave blank to search using the task prompt"
        )
        form.addRow(self.ebay_query_label, self.ebay_query_edit)

        self.ebay_results_label = QLabel("eBay results")
        self.ebay_results_spin = QSpinBox()
        self.ebay_results_spin.setRange(1, 20)
        self.ebay_results_spin.setValue(8)
        form.addRow(self.ebay_results_label, self.ebay_results_spin)

        self.web_search_label = QLabel("Web Search")
        self.web_search_toggle = QPushButton("WEB SEARCH OFF")
        self.web_search_toggle.setCheckable(True)
        self.web_search_toggle.toggled.connect(self._web_search_toggled)
        form.addRow(self.web_search_label, self.web_search_toggle)

        self.web_query_label = QLabel("Search query")
        self.web_query_edit = QLineEdit()
        self.web_query_edit.setPlaceholderText(
            "Optional - leave blank to search using the task prompt"
        )
        form.addRow(self.web_query_label, self.web_query_edit)

        self.web_results_label = QLabel("Search results")
        self.web_results_spin = QSpinBox()
        self.web_results_spin.setRange(1, 10)
        self.web_results_spin.setValue(6)
        form.addRow(self.web_results_label, self.web_results_spin)

        self.web_fetch_label = QLabel("Read pages")
        self.web_fetch_toggle = QPushButton("READ TOP PAGES ON")
        self.web_fetch_toggle.setCheckable(True)
        self.web_fetch_toggle.setChecked(True)
        self.web_fetch_toggle.toggled.connect(
            lambda checked: self.web_fetch_toggle.setText(
                "READ TOP PAGES ON" if checked else "READ TOP PAGES OFF"
            )
        )
        form.addRow(self.web_fetch_label, self.web_fetch_toggle)

        self.data_access_label = QLabel("")
        self.data_access_label.setWordWrap(True)
        self.data_access_label.setStyleSheet(muted_label_style())
        form.addRow("Data access", self.data_access_label)

        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(
            ["Hourly", "Daily", "Weekly", "Custom interval"]
        )
        self.frequency_combo.currentTextChanged.connect(self._frequency_changed)
        form.addRow("Frequency", self.frequency_combo)

        self.every_label = QLabel("Every")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 168)
        self.interval_spin.setValue(1)
        self.interval_spin.setSuffix(" hour(s)")
        form.addRow(self.every_label, self.interval_spin)

        self.weekly_day_label = QLabel("Weekday")
        self.weekly_day_combo = QComboBox()
        self.weekly_day_combo.addItems([
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ])
        form.addRow(self.weekly_day_label, self.weekly_day_combo)

        self.daily_time_label = QLabel("Run time")
        self.daily_time = QTimeEdit()
        self.daily_time.setDisplayFormat("HH:mm")
        self.daily_time.setTime(QTime(8, 0))
        form.addRow(self.daily_time_label, self.daily_time)

        self.custom_interval_label = QLabel("Custom interval")
        custom_interval_row = QHBoxLayout()
        self.custom_interval_spin = QSpinBox()
        self.custom_interval_spin.setRange(1, 10080)
        self.custom_interval_spin.setValue(15)
        self.custom_interval_unit = QComboBox()
        self.custom_interval_unit.addItems(["Minutes", "Hours", "Days"])
        custom_interval_row.addWidget(self.custom_interval_spin, 1)
        custom_interval_row.addWidget(self.custom_interval_unit, 1)
        form.addRow(self.custom_interval_label, custom_interval_row)

        self.enabled_checkbox = QPushButton("ENABLED")
        self.enabled_checkbox.setCheckable(True)
        self.enabled_checkbox.setChecked(True)
        self.enabled_checkbox.toggled.connect(
            lambda checked: self.enabled_checkbox.setText(
                "ENABLED" if checked else "DISABLED"
            )
        )
        form.addRow("State", self.enabled_checkbox)

        right.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(muted_label_style())
        right.addWidget(self.status_label)

        buttons = QHBoxLayout()

        self.save_button = QPushButton("SAVE")
        self.save_button.clicked.connect(self._save_task)
        buttons.addWidget(self.save_button)

        self.run_button = QPushButton("RUN NOW")
        self.run_button.clicked.connect(self._run_now)
        buttons.addWidget(self.run_button)

        self.delete_button = QPushButton("DELETE")
        self.delete_button.clicked.connect(self._delete_task)
        buttons.addWidget(self.delete_button)

        right.addLayout(buttons)

        note = QLabel(
            "Automatic schedules currently run while LocalAI Desktop is open. "
            "Results are written to a dedicated [SCHEDULE] chat."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7F8995;font-size:12px;")
        right.addWidget(note)

        right.addStretch()
        root.addLayout(right, 2)

        self._frequency_changed(self.frequency_combo.currentText())
        self._task_type_changed(self.task_type_combo.currentText())

    def set_models(self, models):
        selected = self.model_combo.currentText() if self.model_combo.count() else ""
        self.models = list(models or [])
        self.model_combo.clear()
        self.model_combo.addItems(self.models)
        if selected:
            index = self.model_combo.findText(selected)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)

    def _schedule_text(self, task):
        frequency = task.get("frequency", "hourly")
        if frequency == "daily":
            return f"daily {task.get('daily_time', '08:00')}"
        if frequency == "weekly":
            weekday = [
                "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
            ][max(0, min(int(task.get("weekly_day", 0) or 0), 6))]
            return f"weekly {weekday} {task.get('daily_time', '08:00')}"
        if frequency == "custom_interval":
            value = task.get("custom_interval_value", 15)
            unit = task.get("custom_interval_unit", "minutes")
            return f"every {value} {unit}"
        return f"every {task.get('interval_hours', 1)}h"

    def _refresh_list(self):
        selected_id = self.current_id
        self.task_list.clear()

        for task in self.store.list_tasks():
            enabled = bool(task.get("enabled", True))
            last_status = task.get("last_status", "never")
            task_type = task.get("task_type", "weather")
            type_label = TASK_TYPES.get(task_type, task_type.upper())

            if last_status == "failed" and enabled:
                dot = "●"
                color = QColor("#D46A72")
            elif enabled:
                dot = "●"
                color = QColor("#78B98C")
            else:
                dot = "○"
                color = QColor("#7F8995")

            next_run = task.get("next_run_at") or "not scheduled"
            text = (
                f"{dot} [{type_label}] {task.get('name', 'Scheduled task')} "
                f"| {self._schedule_text(task)} | next {next_run}"
            )
            item = QListWidgetItem(text)
            item.setForeground(color)
            item.setData(Qt.UserRole, task["id"])
            self.task_list.addItem(item)

            if task["id"] == selected_id:
                self.task_list.setCurrentItem(item)

    def _task_selected(self, item):
        task = self.store.get(item.data(Qt.UserRole))
        self.current_id = task["id"]
        self.name_edit.setText(task.get("name", ""))
        self.prompt_edit.setPlainText(task.get("prompt", ""))
        self.location_edit.setText(task.get("location", ""))
        self.ebay_query_edit.setText(task.get("ebay_query", ""))
        self.ebay_results_spin.setValue(
            max(1, min(int(task.get("ebay_max_results", 8) or 8), 20))
        )
        self.web_search_toggle.setChecked(
            bool(task.get("web_search_enabled", False))
        )
        self.web_query_edit.setText(task.get("web_query", ""))
        self.web_results_spin.setValue(
            max(1, min(int(task.get("web_max_results", 6) or 6), 10))
        )
        self.web_fetch_toggle.setChecked(
            bool(task.get("web_fetch_pages", True))
        )

        task_type = task.get("task_type", "weather")
        self.task_type_combo.setCurrentText(
            TASK_TYPES.get(task_type, "Weather")
        )

        model = task.get("model", "")
        index = self.model_combo.findText(model)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

        frequency = task.get("frequency", "hourly")
        self.frequency_combo.setCurrentText(
            "Custom interval"
            if frequency == "custom_interval"
            else "Weekly"
            if frequency == "weekly"
            else "Daily"
            if frequency == "daily"
            else "Hourly"
        )
        self.interval_spin.setValue(
            max(1, int(task.get("interval_hours", 1) or 1))
        )
        self.weekly_day_combo.setCurrentIndex(
            max(0, min(int(task.get("weekly_day", 0) or 0), 6))
        )
        self.custom_interval_spin.setValue(
            max(1, int(task.get("custom_interval_value", 15) or 15))
        )
        unit = str(task.get("custom_interval_unit", "minutes")).title()
        unit_index = self.custom_interval_unit.findText(unit)
        self.custom_interval_unit.setCurrentIndex(
            unit_index if unit_index >= 0 else 0
        )

        parsed = QTime.fromString(task.get("daily_time", "08:00"), "HH:mm")
        self.daily_time.setTime(parsed if parsed.isValid() else QTime(8, 0))
        self.enabled_checkbox.setChecked(bool(task.get("enabled", True)))
        self.enabled_checkbox.setText(
            "ENABLED" if task.get("enabled", True) else "DISABLED"
        )

        status = task.get("last_status", "never")
        last_run = task.get("last_run_at") or "never"
        last_error = task.get("last_error") or ""
        text = f"Last run: {last_run} | status: {status}"
        if last_error:
            text += f" | error: {last_error}"
        self.status_label.setText(text)
        self._frequency_changed(self.frequency_combo.currentText())
        self._task_type_changed(self.task_type_combo.currentText())

    def _new_task(self):
        self.current_id = ""
        self.name_edit.clear()
        self.prompt_edit.clear()
        self.location_edit.clear()
        self.ebay_query_edit.clear()
        self.ebay_results_spin.setValue(8)
        self.web_search_toggle.setChecked(False)
        self.web_query_edit.clear()
        self.web_results_spin.setValue(6)
        self.web_fetch_toggle.setChecked(True)
        self.task_type_combo.setCurrentText("Weather")
        self.frequency_combo.setCurrentText("Hourly")
        self.interval_spin.setValue(1)
        self.weekly_day_combo.setCurrentIndex(0)
        self.custom_interval_spin.setValue(15)
        self.custom_interval_unit.setCurrentText("Minutes")
        self.daily_time.setTime(QTime(8, 0))
        self.enabled_checkbox.setChecked(True)
        self.enabled_checkbox.setText("ENABLED")
        self.status_label.setText("New task - not saved yet.")
        self._frequency_changed(self.frequency_combo.currentText())
        self._task_type_changed(self.task_type_combo.currentText())

    def _frequency_changed(self, value):
        hourly = value == "Hourly"
        weekly = value == "Weekly"
        custom = value == "Custom interval"

        self.every_label.setVisible(hourly)
        self.interval_spin.setVisible(hourly)
        self.weekly_day_label.setVisible(weekly)
        self.weekly_day_combo.setVisible(weekly)
        self.daily_time_label.setVisible(value in {"Daily", "Weekly"})
        self.daily_time.setVisible(value in {"Daily", "Weekly"})
        self.custom_interval_label.setVisible(custom)
        self.custom_interval_spin.setVisible(custom)
        self.custom_interval_unit.setVisible(custom)

    def _web_search_toggled(self, checked):
        self.web_search_toggle.setText(
            "WEB SEARCH ON" if checked else "WEB SEARCH OFF"
        )
        custom = (
            TYPE_KEYS_BY_LABEL.get(
                self.task_type_combo.currentText(),
                "weather",
            )
            == "custom"
        )
        details = custom and checked
        self.web_query_label.setVisible(details)
        self.web_query_edit.setVisible(details)
        self.web_results_label.setVisible(details)
        self.web_results_spin.setVisible(details)
        self.web_fetch_label.setVisible(details)
        self.web_fetch_toggle.setVisible(details)
        self._update_data_access_text()

    def _update_data_access_text(self):
        task_type = TYPE_KEYS_BY_LABEL.get(
            self.task_type_combo.currentText(),
            "weather",
        )
        descriptions = {
            "weather": (
                "Open-Meteo only: current conditions and a 12-hour forecast "
                "for the configured location."
            ),
            "ebay": (
                "eBay.de public search page only. No login, bidding, buying, "
                "or account access."
            ),
            "computer": (
                "Local machine metrics only: CPU, RAM, GPU/VRAM when available, "
                "and C: disk usage. No internet required."
            ),
            "custom": (
                "Read-only Web Search is enabled. Search results and up to three "
                "public result pages can be passed to the model."
                if self.web_search_toggle.isChecked()
                else
                "Local-only custom task. No live external data source is attached."
            ),
        }
        self.data_access_label.setText(descriptions[task_type])

    def _task_type_changed(self, label):
        task_type = TYPE_KEYS_BY_LABEL.get(label, "weather")
        weather = task_type == "weather"
        ebay = task_type == "ebay"
        custom = task_type == "custom"

        self.location_label.setVisible(weather)
        self.location_edit.setVisible(weather)
        self.ebay_query_label.setVisible(ebay)
        self.ebay_query_edit.setVisible(ebay)
        self.ebay_results_label.setVisible(ebay)
        self.ebay_results_spin.setVisible(ebay)
        self.web_search_label.setVisible(custom)
        self.web_search_toggle.setVisible(custom)

        self._web_search_toggled(
            self.web_search_toggle.isChecked() if custom else False
        )
        self._update_data_access_text()

    def _task_payload(self):
        name = " ".join(self.name_edit.text().strip().split())
        prompt = self.prompt_edit.toPlainText().strip()
        model = self.model_combo.currentText().strip()
        location = " ".join(self.location_edit.text().strip().split())
        ebay_query = " ".join(self.ebay_query_edit.text().strip().split())
        web_query = " ".join(self.web_query_edit.text().strip().split())
        task_type = TYPE_KEYS_BY_LABEL.get(
            self.task_type_combo.currentText(),
            "weather",
        )

        if not name:
            raise ValueError("Task name is required.")
        if not prompt:
            raise ValueError("Prompt is required.")
        if not model:
            raise ValueError("Select an Ollama model.")
        if task_type == "weather" and not location:
            raise ValueError("Weather task requires a location.")

        if self.current_id:
            try:
                task = self.store.get(self.current_id)
            except KeyError:
                task = {}
        else:
            task = {}

        enabled = self.enabled_checkbox.isChecked()
        self.enabled_checkbox.setText("ENABLED" if enabled else "DISABLED")

        frequency = (
            "custom_interval"
            if self.frequency_combo.currentText() == "Custom interval"
            else "weekly"
            if self.frequency_combo.currentText() == "Weekly"
            else "daily"
            if self.frequency_combo.currentText() == "Daily"
            else "hourly"
        )
        web_enabled = (
            task_type == "custom"
            and self.web_search_toggle.isChecked()
        )

        task.update({
            "name": name,
            "task_type": task_type,
            "prompt": prompt,
            "model": model,
            "location": location if task_type == "weather" else "",
            "ebay_query": ebay_query if task_type == "ebay" else "",
            "ebay_max_results": self.ebay_results_spin.value(),
            "web_search_enabled": web_enabled,
            "web_query": web_query if web_enabled else "",
            "web_max_results": self.web_results_spin.value(),
            "web_fetch_pages": self.web_fetch_toggle.isChecked(),
            "frequency": frequency,
            "interval_hours": self.interval_spin.value(),
            "daily_time": self.daily_time.time().toString("HH:mm"),
            "weekly_day": self.weekly_day_combo.currentIndex(),
            "custom_interval_value": self.custom_interval_spin.value(),
            "custom_interval_unit": self.custom_interval_unit.currentText().lower(),
            "enabled": enabled,
            "permissions": {
                "weather": task_type == "weather",
                "ebay": task_type == "ebay",
                "computer": task_type == "computer",
                "web_search": web_enabled,
            },
            "next_run_at": "",
        })
        return task

    def _save_task(self):
        try:
            task = self.store.upsert(self._task_payload())
        except Exception as exc:
            QMessageBox.warning(self, "Schedule", str(exc))
            return None

        self.current_id = task["id"]
        self.status_label.setText(
            f"Saved. Next run: {task.get('next_run_at', '')}"
        )
        self._refresh_list()
        self.tasks_changed.emit()
        return task

    def set_run_status(self, task_id, message, running=False):
        if task_id and self.current_id and task_id != self.current_id:
            return
        self.status_label.setText(message)
        self.run_button.setEnabled(not running)

    def _run_now(self):
        task = self._save_task()
        if task is not None:
            self.set_run_status(
                task["id"],
                "Run requested... waiting for LocalAI.",
                running=True,
            )
            self.run_requested.emit(task["id"])

    def _delete_task(self):
        if not self.current_id:
            return
        self.store.delete(self.current_id)
        self.current_id = ""
        self._refresh_list()
        self._new_task()
        self.tasks_changed.emit()
