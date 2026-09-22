import threading
import time
from dataclasses import dataclass, field


class ExecutionCancelled(RuntimeError):
    pass


class ExecutionBudgetExceeded(RuntimeError):
    pass


class CancellationToken:
    """Thread-safe cancellation signal with active I/O close callbacks."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._callbacks = []

    def is_cancelled(self):
        return self._event.is_set()

    def throw_if_cancelled(self):
        if self.is_cancelled():
            raise ExecutionCancelled("Execution cancelled by user.")

    def register(self, callback):
        if not callable(callback):
            return
        with self._lock:
            if self._event.is_set():
                try:
                    callback()
                except Exception:
                    pass
                return
            self._callbacks.append(callback)

    def unregister(self, callback):
        with self._lock:
            self._callbacks = [
                item for item in self._callbacks if item is not callback
            ]

    def cancel(self):
        self._event.set()
        with self._lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass


@dataclass
class ExecutionBudget:
    timeout_seconds: float = 300.0
    max_model_calls: int = 6
    max_search_calls: int = 4
    max_page_fetches: int = 6
    max_repairs: int = 2
    started_at: float = field(default_factory=time.monotonic)
    model_calls: int = 0
    search_calls: int = 0
    page_fetches: int = 0
    repairs: int = 0

    @property
    def deadline(self):
        return self.started_at + max(1.0, float(self.timeout_seconds))

    def remaining_seconds(self):
        return max(0.0, self.deadline - time.monotonic())

    def check(self, cancellation=None):
        if cancellation is not None:
            cancellation.throw_if_cancelled()
        if self.remaining_seconds() <= 0:
            raise ExecutionBudgetExceeded(
                f"Execution exceeded {self.timeout_seconds:.0f}s deadline."
            )

    def claim_model_call(self, cancellation=None):
        self.check(cancellation)
        if self.model_calls >= int(self.max_model_calls):
            raise ExecutionBudgetExceeded(
                f"Execution exceeded model-call budget ({self.max_model_calls})."
            )
        self.model_calls += 1
        return self.model_calls

    def _claim(self, count_name, maximum_name, label, cancellation=None):
        self.check(cancellation)
        current = int(getattr(self, count_name))
        maximum = int(getattr(self, maximum_name))
        if current >= maximum:
            raise ExecutionBudgetExceeded(
                f"Execution exceeded {label} budget ({maximum})."
            )
        current += 1
        setattr(self, count_name, current)
        return current

    def claim_search(self, cancellation=None):
        return self._claim("search_calls", "max_search_calls", "search-call", cancellation)

    def claim_page_fetch(self, cancellation=None):
        return self._claim("page_fetches", "max_page_fetches", "page-fetch", cancellation)

    def claim_repair(self, cancellation=None):
        return self._claim("repairs", "max_repairs", "repair", cancellation)

    def request_timeout(self, default=600.0, floor=1.0):
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise ExecutionBudgetExceeded(
                f"Execution exceeded {self.timeout_seconds:.0f}s deadline."
            )
        configured_cap = max(1.0, float(self.timeout_seconds))
        return max(
            float(floor),
            min(float(default), configured_cap, remaining),
        )


@dataclass
class ExecutionControl:
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    request_profile: object = None

    @classmethod
    def for_request_profile(cls, profile):
        kind = str(getattr(profile, "kind", "") or "")
        if kind == "direct_fact":
            budget = ExecutionBudget(
                timeout_seconds=45.0,
                max_model_calls=2,
                max_search_calls=1,
                max_page_fetches=1,
                max_repairs=1,
            )
        elif kind == "deep_research":
            budget = ExecutionBudget(
                timeout_seconds=180.0,
                max_model_calls=5,
                max_search_calls=4,
                max_page_fetches=6,
                max_repairs=2,
            )
        else:
            budget = ExecutionBudget(
                timeout_seconds=90.0,
                max_model_calls=4,
                max_search_calls=4,
                max_page_fetches=3,
                max_repairs=2,
            )
        return cls(budget=budget, request_profile=profile)

    def check(self):
        self.budget.check(self.cancellation)

    def claim_model_call(self):
        return self.budget.claim_model_call(self.cancellation)

    def claim_search(self):
        return self.budget.claim_search(self.cancellation)

    def claim_page_fetch(self):
        return self.budget.claim_page_fetch(self.cancellation)

    def claim_repair(self):
        return self.budget.claim_repair(self.cancellation)

    def request_timeout(self, default=600.0):
        self.check()
        return self.budget.request_timeout(default)
