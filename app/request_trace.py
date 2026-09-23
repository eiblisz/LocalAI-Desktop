import json
import os
import threading
import time
import uuid

from .build_identity import build_identity


_SECRET_MARKERS = ("secret", "token", "key", "authorization", "password")


class RequestTrace:
    """Sanitized phase timing for one chat request. Never stores prompt content."""

    def __init__(
        self,
        transport,
        *,
        batch_trace_id=None,
        child_index=None,
        batch_size=None,
    ):
        self.request_id = uuid.uuid4().hex[:12]
        self.transport = str(transport or "unknown")
        self.batch_trace_id = str(batch_trace_id or self.request_id)
        self.child_trace_id = (
            self.request_id if batch_trace_id is not None else None
        )
        self.started_at = time.perf_counter()
        self._lock = threading.RLock()
        self._starts = {}
        self._durations = {}
        self._metadata = {}
        if child_index is not None:
            self.add_metadata(child_index=child_index)
        if batch_size is not None:
            self.add_metadata(batch_size=batch_size)

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

    def add_duration(self, phase, milliseconds):
        with self._lock:
            key = str(phase)
            current = float(self._durations.get(key, 0.0) or 0.0)
            self._durations[key] = round(
                current + float(milliseconds or 0.0),
                2,
            )

    def add_metadata(self, **metadata):
        for key, value in metadata.items():
            lowered = str(key).casefold()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                self._metadata[str(key)] = value

    def snapshot(self):
        with self._lock:
            identity = build_identity()
            return {
                "request_id": self.request_id,
                "batch_trace_id": self.batch_trace_id,
                "child_trace_id": self.child_trace_id,
                "transport": self.transport,
                **identity,
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
