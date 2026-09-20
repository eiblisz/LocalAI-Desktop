import argparse
import logging
import time
from logging.handlers import RotatingFileHandler

from .config import SCHEDULE_DIR
from .scheduler_engine import SchedulerEngine


def _configure_logging():
    log_path = SCHEDULE_DIR / "runner.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger = logging.getLogger("localai.scheduler_runner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def run_once(engine=None, logger=None):
    engine = engine or SchedulerEngine()
    logger = logger or _configure_logging()
    result = engine.run_once()

    if result.status == "idle":
        logger.debug("No due scheduled task.")
    elif result.status == "success":
        logger.info(
            "Scheduled task completed task_id=%s attempt_id=%s %s",
            result.task_id,
            result.attempt_id,
            result.message,
        )
    elif result.status == "stale":
        logger.warning(
            "Stale scheduler attempt ignored task_id=%s attempt_id=%s %s",
            result.task_id,
            result.attempt_id,
            result.message,
        )
    else:
        logger.error(
            "Scheduled task failed task_id=%s attempt_id=%s %s",
            result.task_id,
            result.attempt_id,
            result.message,
        )
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="LocalAI Desktop background scheduler runner."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Check and execute at most one due task, then exit.",
    )
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Stay alive and continuously execute due tasks.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Idle polling interval in seconds for loop mode.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=3600,
        help="Execution lease duration used to recover from crashed runners.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    logger = _configure_logging()
    engine = SchedulerEngine(lease_seconds=args.lease_seconds)

    if not args.loop:
        result = run_once(engine, logger)
        return 1 if result.status == "failed" else 0

    interval = max(5, int(args.interval or 30))
    logger.info(
        "LocalAI scheduler runner started owner_id=%s interval=%ss",
        engine.owner_id,
        interval,
    )

    try:
        while True:
            result = run_once(engine, logger)
            if result.status == "idle":
                time.sleep(interval)
            else:
                # Drain another already-due task without waiting a full interval.
                time.sleep(0.25)
    except KeyboardInterrupt:
        logger.info("LocalAI scheduler runner stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
