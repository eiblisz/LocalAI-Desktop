from pathlib import Path
from types import SimpleNamespace

from app import scheduler_runner


ROOT = Path(__file__).resolve().parents[1]


class DummyLogger:
    def __init__(self):
        self.events = []

    def debug(self, *args):
        self.events.append(("debug", args))

    def info(self, *args):
        self.events.append(("info", args))

    def warning(self, *args):
        self.events.append(("warning", args))

    def error(self, *args):
        self.events.append(("error", args))


class DummyEngine:
    def __init__(self, result):
        self.result = result

    def run_once(self):
        return self.result


def test_runner_once_reports_idle_without_error():
    logger = DummyLogger()
    result = scheduler_runner.run_once(
        DummyEngine(SimpleNamespace(
            status="idle",
            task_id="",
            attempt_id="",
            message="",
        )),
        logger,
    )

    assert result.status == "idle"
    assert logger.events[-1][0] == "debug"


def test_runner_once_logs_success_and_failure():
    success_logger = DummyLogger()
    scheduler_runner.run_once(
        DummyEngine(SimpleNamespace(
            status="success",
            task_id="task-a",
            attempt_id="attempt-a",
            message="[SCHEDULE] A",
        )),
        success_logger,
    )
    assert success_logger.events[-1][0] == "info"

    failure_logger = DummyLogger()
    scheduler_runner.run_once(
        DummyEngine(SimpleNamespace(
            status="failed",
            task_id="task-b",
            attempt_id="attempt-b",
            message="boom",
        )),
        failure_logger,
    )
    assert failure_logger.events[-1][0] == "error"


def test_runner_cli_defaults_to_single_bounded_check():
    args = scheduler_runner.build_parser().parse_args([])

    assert args.loop is False
    assert args.once is False
    assert args.interval == 30
    assert args.lease_seconds == 3600


def test_windows_registration_scripts_use_background_runner_and_single_instance():
    register = (
        ROOT / "scripts" / "register_scheduler_runner.ps1"
    ).read_text(encoding="utf-8")
    unregister = (
        ROOT / "scripts" / "unregister_scheduler_runner.ps1"
    ).read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in register
    assert "-m app.scheduler_runner --loop --interval" in register
    assert "New-ScheduledTaskTrigger -AtLogOn" in register
    assert "-MultipleInstances IgnoreNew" in register
    assert "-RestartCount 999" in register
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in register
    assert "Register-ScheduledTask" in register
    assert "Start-ScheduledTask" in register

    assert "Stop-ScheduledTask" in unregister
    assert "Unregister-ScheduledTask" in unregister
