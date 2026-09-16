import inspect

from app.scheduler_dialog import SchedulerDialog


def test_frequency_switch_hides_irrelevant_timing_controls():
    source = inspect.getsource(SchedulerDialog._frequency_changed)

    assert "self.every_label.setVisible(not daily)" in source
    assert "self.interval_spin.setVisible(not daily)" in source
    assert "self.daily_time_label.setVisible(daily)" in source
    assert "self.daily_time.setVisible(daily)" in source
