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
    started_at: float = field(default_factory=time.monotonic)
    model_calls: int = 0

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

    def request_timeout(self, default=600.0, floor=1.0):
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise ExecutionBudgetExceeded(
                f"Execution exceeded {self.timeout_seconds:.0f}s deadline."
            )
        return max(float(floor), min(float(default), remaining))


@dataclass
class ExecutionControl:
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    def check(self):
        self.budget.check(self.cancellation)

    def claim_model_call(self):
        return self.budget.claim_model_call(self.cancellation)

    def request_timeout(self, default=600.0):
        self.check()
        return self.budget.request_timeout(default)
