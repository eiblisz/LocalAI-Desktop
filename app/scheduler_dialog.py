from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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


class SchedulerDialog(QDialog):
    run_requested = Signal(str)
    tasks_changed = Signal()

    def __init__(self, store: ScheduledTaskStore, models=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.models = list(models or [])
        self.current_id = ""

        self.setWindowTitle("Scheduled Tasks")
        self.resize(820, 640)
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
            "Scheduled tasks can use only explicitly enabled tools. "
            "Weather uses Open-Meteo; the local model itself has no direct internet access."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#9099A6;")
        right.addWidget(intro)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Example: Hourly weather check")
        form.addRow("Task name", self.name_edit)

        self.model_combo = QComboBox()
        form.addRow("Model", self.model_combo)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Example: Check the weather and tell me only if rain is likely."
        )
        self.prompt_edit.setFixedHeight(115)
        form.addRow("Prompt", self.prompt_edit)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Example: Bad Nenndorf, Germany")
        form.addRow("Weather location", self.location_edit)

        self.frequency_combo = QComboBox()
        self.frequency_combo.addItems(["Hourly", "Daily"])
        self.frequency_combo.currentTextChanged.connect(self._frequency_changed)
        form.addRow("Frequency", self.frequency_combo)

        self.every_label = QLabel("Every")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 168)
        self.interval_spin.setValue(1)
        self.interval_spin.setSuffix(" hour(s)")
        form.addRow(self.every_label, self.interval_spin)

        self.daily_time_label = QLabel("Daily time")
        self.daily_time = QTimeEdit()
        self.daily_time.setDisplayFormat("HH:mm")
        self.daily_time.setTime(QTime(8, 0))
        form.addRow(self.daily_time_label, self.daily_time)

        self.weather_checkbox = QCheckBox("Allow Weather internet tool (Open-Meteo)")
        self.weather_checkbox.setChecked(True)
        form.addRow("Permissions", self.weather_checkbox)

        self.enabled_checkbox = QCheckBox("Enabled")
        self.enabled_checkbox.setChecked(True)
        form.addRow("State", self.enabled_checkbox)

        right.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#9099A6;")
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
            "MVP behavior: automatic schedules run while LocalAI Desktop is open. "
            "Results are written to a dedicated [SCHEDULE] chat."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7F8995;font-size:12px;")
        right.addWidget(note)

        right.addStretch()
        root.addLayout(right, 2)

        self._frequency_changed(self.frequency_combo.currentText())

    def set_models(self, models):
        selected = self.model_combo.currentText() if self.model_combo.count() else ""
        self.models = list(models or [])
        self.model_combo.clear()
        self.model_combo.addItems(self.models)
        if selected:
            index = self.model_combo.findText(selected)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)

    def _refresh_list(self):
        selected_id = self.current_id
        self.task_list.clear()

        for task in self.store.list_tasks():
            state = "ON" if task.get("enabled", True) else "OFF"
            if task.get("frequency") == "daily":
                schedule = f"daily {task.get('daily_time', '08:00')}"
            else:
                schedule = f"every {task.get('interval_hours', 1)}h"

            next_run = task.get("next_run_at") or "not scheduled"
            text = f"[{state}] {task.get('name', 'Scheduled task')} | {schedule} | next {next_run}"
            item = QListWidgetItem(text)
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

        model = task.get("model", "")
        index = self.model_combo.findText(model)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

        daily = task.get("frequency") == "daily"
        self.frequency_combo.setCurrentText("Daily" if daily else "Hourly")
        self.interval_spin.setValue(max(1, int(task.get("interval_hours", 1) or 1)))

        parsed = QTime.fromString(task.get("daily_time", "08:00"), "HH:mm")
        self.daily_time.setTime(parsed if parsed.isValid() else QTime(8, 0))

        permissions = task.get("permissions") or {}
        self.weather_checkbox.setChecked(bool(permissions.get("weather", False)))
        self.enabled_checkbox.setChecked(bool(task.get("enabled", True)))

        status = task.get("last_status", "never")
        last_run = task.get("last_run_at") or "never"
        last_error = task.get("last_error") or ""
        text = f"Last run: {last_run} | status: {status}"
        if last_error:
            text += f" | error: {last_error}"
        self.status_label.setText(text)

    def _new_task(self):
        self.current_id = ""
        self.name_edit.clear()
        self.prompt_edit.clear()
        self.location_edit.clear()
        self.frequency_combo.setCurrentText("Hourly")
        self.interval_spin.setValue(1)
        self.daily_time.setTime(QTime(8, 0))
        self.weather_checkbox.setChecked(True)
        self.enabled_checkbox.setChecked(True)
        self.status_label.setText("New task - not saved yet.")
        self._frequency_changed(self.frequency_combo.currentText())

    def _frequency_changed(self, value):
        daily = value == "Daily"
        self.every_label.setVisible(not daily)
        self.interval_spin.setVisible(not daily)
        self.daily_time_label.setVisible(daily)
        self.daily_time.setVisible(daily)

    def _task_payload(self):
        name = " ".join(self.name_edit.text().strip().split())
        prompt = self.prompt_edit.toPlainText().strip()
        model = self.model_combo.currentText().strip()
        location = " ".join(self.location_edit.text().strip().split())

        if not name:
            raise ValueError("Task name is required.")
        if not prompt:
            raise ValueError("Prompt is required.")
        if not model:
            raise ValueError("Select an Ollama model.")
        if not self.weather_checkbox.isChecked():
            raise ValueError(
                "Enable at least one data tool. Weather is the available tool in this version."
            )
        if not location:
            raise ValueError("Weather permission requires a location.")

        if self.current_id:
            try:
                task = self.store.get(self.current_id)
            except KeyError:
                task = {}
        else:
            task = {}

        task.update({
            "name": name,
            "prompt": prompt,
            "model": model,
            "location": location,
            "frequency": (
                "daily"
                if self.frequency_combo.currentText() == "Daily"
                else "hourly"
            ),
            "interval_hours": self.interval_spin.value(),
            "daily_time": self.daily_time.time().toString("HH:mm"),
            "enabled": self.enabled_checkbox.isChecked(),
            "permissions": {
                "weather": self.weather_checkbox.isChecked(),
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
