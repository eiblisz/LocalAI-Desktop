from app.orchestration_benchmark import run_host_orchestration_benchmark


def test_host_orchestration_benchmark_passes_all_cases():
    report = run_host_orchestration_benchmark()

    assert report.failed == 0
    assert report.passed == report.total == 5
    assert {item.name for item in report.results} == {
        "parent_task_binding",
        "web_mode_routing",
        "language_script_guard",
        "context_entity_drift",
        "runtime_budget",
    }


def test_benchmark_report_is_machine_readable():
    report = run_host_orchestration_benchmark().to_dict()

    assert report["failed"] == 0
    assert report["total"] == 5
    assert len(report["results"]) == 5
    assert all("name" in item and "passed" in item for item in report["results"])
