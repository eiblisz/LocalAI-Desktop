import inspect

from app.scheduler_dialog import SchedulerDialog, TASK_TYPES


def test_frequency_switch_hides_irrelevant_timing_controls():
    source = inspect.getsource(SchedulerDialog._frequency_changed)

    assert 'hourly = value == "Hourly"' in source
    assert 'weekly = value == "Weekly"' in source
    assert "self.every_label.setVisible(hourly)" in source
    assert "self.interval_spin.setVisible(hourly)" in source
    assert "self.weekly_day_label.setVisible(weekly)" in source
    assert "self.weekly_day_combo.setVisible(weekly)" in source
    assert "self.daily_time.setVisible(not hourly)" in source


def test_task_type_switch_controls_source_specific_fields():
    source = inspect.getsource(SchedulerDialog._task_type_changed)

    assert 'task_type == "weather"' in source
    assert 'task_type == "ebay"' in source
    assert "self.location_edit.setVisible(weather)" in source
    assert "self.ebay_query_edit.setVisible(ebay)" in source
    assert '"computer"' in source
    assert '"custom"' in source


def test_scheduler_exposes_four_automation_types():
    assert TASK_TYPES == {
        "weather": "Weather",
        "ebay": "eBay Search",
        "computer": "Computer Status",
        "custom": "Custom",
    }


def test_scheduler_frequency_list_includes_weekly():
    source = inspect.getsource(SchedulerDialog._build_ui)
    assert '["Hourly", "Daily", "Weekly"]' in source
