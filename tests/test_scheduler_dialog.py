import inspect

from app.scheduler_dialog import SchedulerDialog


def test_frequency_switch_hides_irrelevant_timing_controls():
    source = inspect.getsource(SchedulerDialog._frequency_changed)

    assert "self.every_label.setVisible(not daily)" in source
    assert "self.interval_spin.setVisible(not daily)" in source
    assert "self.daily_time_label.setVisible(daily)" in source
    assert "self.daily_time.setVisible(daily)" in source


def test_task_type_switch_controls_source_specific_fields():
    source = inspect.getsource(SchedulerDialog._task_type_changed)

    assert 'task_type == "weather"' in source
    assert 'task_type == "ebay"' in source
    assert "self.location_edit.setVisible(weather)" in source
    assert "self.ebay_query_edit.setVisible(ebay)" in source
    assert "COMPUTER" not in source.upper() or "computer" in source


def test_scheduler_exposes_four_automation_types():
    from app.scheduler_dialog import TASK_TYPES

    assert TASK_TYPES == {
        "weather": "Weather",
        "ebay": "eBay Search",
        "computer": "Computer Status",
        "custom": "Custom",
    }
