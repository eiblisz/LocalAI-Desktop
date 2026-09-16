import inspect

from app.scheduler_dialog import SchedulerDialog, TASK_TYPES


def test_frequency_switch_hides_irrelevant_timing_controls():
    source = inspect.getsource(SchedulerDialog._frequency_changed)

    assert 'hourly = value == "Hourly"' in source
    assert 'weekly = value == "Weekly"' in source
    assert 'custom = value == "Custom interval"' in source
    assert "self.every_label.setVisible(hourly)" in source
    assert "self.interval_spin.setVisible(hourly)" in source
    assert "self.weekly_day_label.setVisible(weekly)" in source
    assert "self.weekly_day_combo.setVisible(weekly)" in source
    assert 'self.daily_time.setVisible(value in {"Daily", "Weekly"})' in source
    assert "self.custom_interval_spin.setVisible(custom)" in source
    assert "self.custom_interval_unit.setVisible(custom)" in source


def test_task_type_switch_controls_source_specific_fields():
    source = inspect.getsource(SchedulerDialog._task_type_changed)

    assert 'task_type == "weather"' in source
    assert 'task_type == "ebay"' in source
    assert 'task_type == "custom"' in source
    assert "self.location_edit.setVisible(weather)" in source
    assert "self.ebay_query_edit.setVisible(ebay)" in source
    assert "self.web_search_toggle.setVisible(custom)" in source


def test_scheduler_exposes_four_automation_types():
    assert TASK_TYPES == {
        "weather": "Weather",
        "ebay": "eBay Search",
        "computer": "Computer Status",
        "custom": "Custom",
    }


def test_scheduler_frequency_list_includes_weekly_and_custom_interval():
    source = inspect.getsource(SchedulerDialog._build_ui)
    assert "Hourly" in source
    assert "Daily" in source
    assert "Weekly" in source
    assert "Custom interval" in source


def test_scheduler_list_does_not_predeclare_task_categories():
    source = inspect.getsource(SchedulerDialog._build_ui)

    assert "type_status_labels" not in source
    assert "TASK_TYPES.items()" not in source
    assert "self.task_list = QListWidget()" in source


def test_custom_frequency_shows_interval_controls():
    source = inspect.getsource(SchedulerDialog._frequency_changed)

    assert 'custom = value == "Custom interval"' in source
    assert "self.custom_interval_spin.setVisible(custom)" in source
    assert "self.custom_interval_unit.setVisible(custom)" in source


def test_custom_task_can_toggle_web_search_fields():
    source = inspect.getsource(SchedulerDialog._web_search_toggled)
    payload = inspect.getsource(SchedulerDialog._task_payload)

    assert "WEB SEARCH ON" in source
    assert "self.web_query_edit.setVisible(details)" in source
    assert '"web_search_enabled": web_enabled' in payload
    assert '"web_fetch_pages": self.web_fetch_toggle.isChecked()' in payload
