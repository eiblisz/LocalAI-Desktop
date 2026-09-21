import json
import sys

from app.orchestration_benchmark import run_host_orchestration_benchmark


def main():
    report = run_host_orchestration_benchmark()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
