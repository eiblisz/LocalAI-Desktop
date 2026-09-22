import json
import os
import threading
import time
import uuid


_SECRET_MARKERS = ("secret", "token", "key", "authorization", "password")


class RequestTrace:
    """Sanitized phase timing for one chat request. Never stores prompt content."""

    def __init__(self, transport):
        self.request_id = uuid.uuid4().hex[:12]
        self.transport = str(transport or "unknown")
        self.started_at = time.perf_counter()
        self._lock = threading.RLock()
        self._starts = {}
        self._durations = {}
        self._metadata = {}

    def begin(self, phase):
        with self._lock:
            self._starts[str(phase)] = time.perf_counter()

    def end(self, phase, **metadata):
        phase = str(phase)
        with self._lock:
            started = self._starts.pop(phase, None)
            if started is not None:
                self._durations[phase] = round(
                    (time.perf_counter() - started) * 1000,
                    2,
                )
            self.add_metadata(**metadata)

    def mark_duration(self, phase, milliseconds):
        with self._lock:
            self._durations[str(phase)] = round(float(milliseconds or 0.0), 2)

    def add_metadata(self, **metadata):
        for key, value in metadata.items():
            lowered = str(key).casefold()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                self._metadata[str(key)] = value

    def snapshot(self):
        with self._lock:
            return {
                "request_id": self.request_id,
                "transport": self.transport,
                "total_ms": round(
                    (time.perf_counter() - self.started_at) * 1000,
                    2,
                ),
                "phases_ms": dict(self._durations),
                "metadata": dict(self._metadata),
            }

    def emit_if_enabled(self):
        if os.environ.get("LOCALAI_TIMING_LOG", "").strip().lower() not in {
            "1", "true", "yes", "on",
        }:
            return
        print(
            "LOCALAI_TIMING " + json.dumps(
                self.snapshot(),
                ensure_ascii=True,
                sort_keys=True,
            ),
            flush=True,
        )
