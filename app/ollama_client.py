import json
import os
import threading
import uuid
from typing import Callable

import requests

from .config import OLLAMA_BASE_URL, OLLAMA_NUM_PREDICT, OLLAMA_THINKING_ENABLED
from .ollama_process_control import (
    list_external_ollama_consumers,
    list_ollama_model_processes,
)
from .ollama_resource_coordinator import (
    OWNER_UNKNOWN,
    STATE_ERROR,
    STATE_IDLE,
    STATE_INFERENCE_ACTIVE,
    STATE_MODEL_LOADING,
    STATE_STALE,
    OllamaResourceBusyError,
    ResourceLeaseStore,
)
from .vram_release import loaded_ollama_models, unload_ollama_model


class IncompleteGenerationError(RuntimeError):
    pass


def _tag_ollama_failure(
    exc,
    *,
    stage,
    classification,
    request_sequence=None,
    call_phase=None,
):
    """Attach safe, machine-readable context without replacing the root error."""
    try:
        exc.localai_failure_stage = str(stage)
        exc.localai_failure_classification = str(classification)
        if request_sequence is not None:
            exc.localai_ollama_request_sequence = int(request_sequence)
            exc.localai_ollama_initial_request = int(request_sequence) == 1
        if call_phase:
            exc.localai_ollama_call_phase = str(call_phase)
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            exc.localai_ollama_http_status = int(status)
    except Exception:
        pass
    return exc


def ollama_failure_metadata(exc):
    """Return trace-safe failure classification for a caught Ollama error."""
    stage = str(getattr(exc, "localai_failure_stage", "") or "")
    classification = str(
        getattr(exc, "localai_failure_classification", "") or ""
    )
    if not stage:
        if isinstance(exc, IncompleteGenerationError):
            stage = "stream_completion"
            classification = "incomplete_generation"
        elif isinstance(exc, requests.Timeout):
            stage = "ollama_transport"
            classification = "transport_timeout"
        elif isinstance(exc, requests.ConnectionError):
            stage = "ollama_transport"
            classification = "transport_connection"
        elif isinstance(exc, requests.HTTPError):
            stage = "ollama_http"
            classification = "http_status"
        elif isinstance(exc, requests.RequestException):
            stage = "ollama_transport"
            classification = "transport_error"
        elif isinstance(exc, OllamaResourceBusyError):
            stage = "model_preparation"
            classification = "model_resource_safety"
        else:
            stage = "unknown"
            classification = "unexpected_execution_error"

    metadata = {
        "ollama_failure_stage": stage,
        "ollama_failure_classification": classification,
    }
    for attribute, key in (
        ("localai_ollama_request_sequence", "ollama_request_sequence"),
        ("localai_ollama_initial_request", "ollama_initial_request"),
        ("localai_ollama_http_status", "ollama_http_status"),
        ("localai_ollama_call_phase", "ollama_call_phase"),
    ):
        value = getattr(exc, attribute, None)
        if value is not None:
            metadata[key] = value
    return metadata


def _request_failure_details(exc):
    if isinstance(exc, requests.Timeout):
        return "ollama_transport", "transport_timeout"
    if isinstance(exc, requests.ConnectionError):
        return "ollama_transport", "transport_connection"
    if isinstance(exc, requests.HTTPError):
        return "ollama_http", "http_status"
    if isinstance(exc, requests.RequestException):
        return "ollama_transport", "transport_error"
    return "model_inference", "model_request_failed"


class OllamaClient:
    # The shared response guard may use strict JSON for a bounded fluency audit.
    supports_hungarian_fluency_audit = True

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        *,
        auto_prepare_model: bool = False,
        owner_type: str = OWNER_UNKNOWN,
        owner_id: str = "",
        resource_store=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auto_prepare_model = bool(auto_prepare_model)
        self.owner_type = str(owner_type or OWNER_UNKNOWN).strip().upper()
        self.owner_id = str(owner_id or "").strip() or (
            f"{self.owner_type.lower()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
        self.resource_store = resource_store or ResourceLeaseStore()
        self._request_sequence_lock = threading.Lock()
        self._request_sequence = 0

    def _next_request_sequence(self):
        with self._request_sequence_lock:
            self._request_sequence += 1
            return self._request_sequence

    def is_available(self, timeout: float = 2.0) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            return response.ok
        except requests.RequestException:
            return False

    def list_models(self, timeout: float = 5.0) -> list[str]:
        response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return [item["name"] for item in payload.get("models", []) if item.get("name")]

    @staticmethod
    def _busy_message(model, ownership):
        owner = str((ownership or {}).get("owner") or OWNER_UNKNOWN)
        state = str((ownership or {}).get("state") or "UNKNOWN")
        return (
            f"Ollama model '{model}' is a shared resource owned by "
            f"{owner} ({state}). LocalAI Desktop will not stop it."
        )

    def _runner_processes(self):
        try:
            return list_ollama_model_processes(timeout=3.0)
        except Exception:
            return None

    def _external_consumers(self):
        try:
            return list_external_ollama_consumers(
                timeout=3.0,
                exclude_pids=[os.getpid()],
            )
        except Exception:
            return None

    def _assert_external_switch_safe(self, target):
        external = self._external_consumers()
        if external is None:
            raise OllamaResourceBusyError(
                "Could not verify external Ollama consumers; model switch is blocked."
            )

        conflicts = []
        for item in external:
            owner = str(item.get("owner") or OWNER_UNKNOWN)
            model = str(item.get("model") or "").strip()

            # Sharing the exact same model with a visible manual CLI is not a
            # destructive switch. Any different or unknown external use blocks.
            if owner == "MANUAL" and model and model == target:
                continue
            conflicts.append(item)

        if conflicts:
            first = conflicts[0]
            owner = str(first.get("owner") or OWNER_UNKNOWN)
            model = str(first.get("model") or "").strip() or "unknown model"
            raise OllamaResourceBusyError(
                f"Ollama is in use by another local owner ({owner}, {model}); "
                "model switch is blocked rather than stopping shared runtime state."
            )
        return external

    def _observed_model_pid(self):
        processes = self._runner_processes()
        if processes is None or len(processes) != 1:
            return None
        return processes[0].get("pid")

    def _set_request_state(
        self,
        model,
        request_id,
        state,
        detail="",
        *,
        observe_pid=False,
    ):
        if self.owner_type == OWNER_UNKNOWN:
            return None
        return self.resource_store.upsert(
            owner=self.owner_type,
            owner_id=self.owner_id,
            model=model,
            state=state,
            owner_pid=os.getpid(),
            model_pid=(self._observed_model_pid() if observe_pid else None),
            request_id=request_id,
            detail=detail,
        )

    def prepare_model(self, model: str, timeout: float = 6.0) -> list[str]:
        """
        Gracefully unload only a provably self-owned idle stale model.

        Unknown or foreign ownership is fail-closed. This method never kills a
        runner or restarts the shared Ollama server.
        """
        target = str(model or "").strip()
        if not target:
            raise ValueError("A target Ollama model is required.")

        # Check external consumers before trusting /api/ps. A manual
        # "ollama run" session may be visible as a client even while its model
        # is not momentarily reported as resident.
        self._assert_external_switch_safe(target)

        try:
            loaded = loaded_ollama_models(
                self,
                timeout=min(float(timeout), 2.5),
            )
        except requests.RequestException as exc:
            raise OllamaResourceBusyError(
                "Ollama runtime state is unavailable; automatic recovery is disabled "
                "for shared-resource safety."
            ) from exc

        stale = [name for name in loaded if name and name != target]
        if not stale:
            return []

        runners = self._runner_processes()
        if runners == []:
            for name in stale:
                self.resource_store.mark_stale(
                    name,
                    detail="runtime reconciliation: model listed but no runner process exists",
                )
            return []
        if runners is None:
            raise OllamaResourceBusyError(
                "Could not verify Ollama runner ownership; model switch is blocked."
            )

        # Re-check immediately before any unload to close the race between
        # runtime inspection and destructive preparation.
        self._assert_external_switch_safe(target)

        released = []
        for name in stale:
            allowed, ownership = self.resource_store.can_control_model(
                owner=self.owner_type,
                owner_id=self.owner_id,
                model=name,
                allow_active=False,
            )
            if not allowed:
                raise OllamaResourceBusyError(
                    self._busy_message(name, ownership)
                )
            unload_ollama_model(
                self,
                name,
                timeout=min(float(timeout), 5.0),
            )
            self.resource_store.mark_stale(
                name,
                detail=f"gracefully unloaded by {self.owner_type}",
            )
            released.append(name)
        return released

    def release_owned_models(self, timeout: float = 5.0):
        """Gracefully release only models with proven idle ownership."""
        try:
            loaded = loaded_ollama_models(
                self,
                timeout=min(float(timeout), 3.0),
            )
        except requests.RequestException as exc:
            raise OllamaResourceBusyError(
                "Ollama runtime state is unavailable; FREE VRAM is blocked."
            ) from exc

        runners = self._runner_processes()
        if runners == []:
            for name in loaded:
                self.resource_store.mark_stale(
                    name,
                    detail="runtime reconciliation: no runner process exists",
                )
            return {"released": [], "blocked": [], "reconciled": list(loaded)}
        if runners is None:
            return {
                "released": [],
                "blocked": [
                    {
                        "model": name,
                        "owner": OWNER_UNKNOWN,
                        "state": "UNKNOWN",
                    }
                    for name in loaded
                ],
                "reconciled": [],
            }

        external = self._external_consumers()
        if external is None or external:
            owner = (
                external[0].get("owner", OWNER_UNKNOWN)
                if external
                else OWNER_UNKNOWN
            )
            return {
                "released": [],
                "blocked": [
                    {
                        "model": name,
                        "owner": owner,
                        "state": "EXTERNAL_OR_UNKNOWN",
                    }
                    for name in loaded
                ],
                "reconciled": [],
            }

        released = []
        blocked = []
        for name in loaded:
            allowed, ownership = self.resource_store.can_control_model(
                owner=self.owner_type,
                owner_id=self.owner_id,
                model=name,
                allow_active=False,
            )
            if not allowed:
                blocked.append(
                    {
                        "model": name,
                        "owner": ownership.get("owner", OWNER_UNKNOWN),
                        "state": ownership.get("state", "UNKNOWN"),
                    }
                )
                continue
            unload_ollama_model(self, name, timeout=min(float(timeout), 5.0))
            self.resource_store.mark_stale(
                name,
                detail=f"FREE VRAM by {self.owner_type}",
            )
            released.append(name)
        return {"released": released, "blocked": blocked, "reconciled": []}

    def owned_model_process_ids(self, model="", *, allow_active=True):
        models = [str(model or "").strip()] if str(model or "").strip() else []
        leases = (
            self.resource_store.leases_for_model(models[0])
            if models
            else self.resource_store.list_leases()
        )
        pids = []
        for lease in leases:
            if (
                lease.get("owner") != self.owner_type
                or lease.get("owner_id") != self.owner_id
            ):
                continue
            if lease.get("state") == STATE_STALE:
                continue
            if (
                lease.get("state") == STATE_INFERENCE_ACTIVE
                and not allow_active
            ):
                continue
            pid = lease.get("model_pid")
            if isinstance(pid, int) and pid > 0:
                pids.append(pid)
        return sorted(set(pids))

    def foreign_active_leases(self):
        return self.resource_store.foreign_active_leases(
            owner=self.owner_type,
            owner_id=self.owner_id,
        )

    def chat_once(
        self,
        model: str,
        messages: list[dict],
        timeout: float = 600.0,
        response_format=None,
        control=None,
        num_predict=None,
        call_phase=None,
    ) -> str:
        call_phase = str(call_phase or "model_inference")
        request_sequence = self._next_request_sequence()
        if control is not None:
            control.claim_model_call()
            timeout = control.request_timeout(timeout)

        if self.auto_prepare_model:
            try:
                self.prepare_model(model)
            except Exception as exc:
                raise _tag_ollama_failure(
                    exc,
                    stage="model_preparation",
                    classification="model_prepare_failed",
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                )

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        output_budget = (
            OLLAMA_NUM_PREDICT
            if num_predict is None
            else max(1, int(num_predict))
        )
        structured_response = response_format is not None
        payload = {
            "model": model,
            "messages": messages,
            # Structured JSON helper calls are intentionally non-streaming.
            # Ollama can occasionally close a structured stream after emitting
            # complete JSON but before its terminal done marker. The caller
            # validates the full JSON contract, so avoid that transport-level
            # false failure while retaining controlled streaming for ordinary
            # chat generation.
            "stream": bool(control is not None and not structured_response),
            # Recent Ollama thinking-capable models, including the preferred
            # Gemma model, otherwise spend tokens on hidden reasoning before
            # they emit a visible answer.  The explicit request is harmless
            # for ordinary models and can be opt-in overridden by the operator.
            "think": OLLAMA_THINKING_ENABLED,
            "options": {"num_predict": output_budget},
        }
        if response_format is not None:
            if not isinstance(response_format, (str, dict)):
                raise TypeError("response_format must be a string, object, or None.")
            payload["format"] = response_format

        try:
            self._set_request_state(model, request_id, STATE_INFERENCE_ACTIVE)
            if control is None or structured_response:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                if control is not None:
                    control.check()
                item = response.json()
                result = item.get("message", {}).get("content", "")
            else:
                parts = []
                item = {}
                with requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    stream=True,
                    timeout=timeout,
                ) as response:
                    close_callback = response.close
                    control.cancellation.register(close_callback)
                    if control.cancellation.is_cancelled():
                        return ""
                    response.raise_for_status()
                    try:
                        for raw_line in response.iter_lines():
                            control.check()
                            if not raw_line:
                                continue
                            item = json.loads(raw_line.decode("utf-8"))
                            chunk = item.get("message", {}).get("content", "")
                            if chunk:
                                parts.append(chunk)
                            if item.get("done"):
                                break
                    finally:
                        control.cancellation.unregister(close_callback)
                result = "".join(parts)
                if not control.cancellation.is_cancelled() and not item.get("done"):
                    raise _tag_ollama_failure(
                        IncompleteGenerationError(
                            "Ollama ended the response stream without a completion marker; "
                            "the incomplete response was rejected."
                        ),
                        stage="stream_completion",
                        classification="stream_terminated_without_completion",
                        request_sequence=request_sequence,
                        call_phase=call_phase,
                    )
            if str(item.get("done_reason") or "").strip().lower() == "length":
                raise _tag_ollama_failure(
                    IncompleteGenerationError(
                        "Ollama stopped at the configured output-token limit; "
                        "the incomplete response was rejected."
                    ),
                    stage="generation_length",
                    classification="output_token_limit",
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                )
        except Exception as exc:
            if not getattr(exc, "localai_failure_stage", ""):
                stage, classification = _request_failure_details(exc)
                _tag_ollama_failure(
                    exc,
                    stage=stage,
                    classification=classification,
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                )
            self._set_request_state(
                model,
                request_id,
                STATE_ERROR,
                detail=str(exc),
                observe_pid=True,
            )
            raise
        else:
            self._set_request_state(
                model,
                request_id,
                STATE_IDLE,
                observe_pid=True,
            )
            return result

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        on_token: Callable[[str], None],
        should_stop: Callable[[], bool],
        timeout: float = 600.0,
        control=None,
        num_predict=None,
        call_phase=None,
    ) -> None:
        call_phase = str(call_phase or "model_inference")
        request_sequence = self._next_request_sequence()
        if control is not None:
            control.claim_model_call()
            timeout = control.request_timeout(timeout)

        if self.auto_prepare_model:
            try:
                self.prepare_model(model)
            except Exception as exc:
                raise _tag_ollama_failure(
                    exc,
                    stage="model_preparation",
                    classification="model_prepare_failed",
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                )

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        output_budget = (
            OLLAMA_NUM_PREDICT
            if num_predict is None
            else max(1, int(num_predict))
        )
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": OLLAMA_THINKING_ENABLED,
            "options": {"num_predict": output_budget},
        }
        final_item = {}
        done_reason = ""
        stopped = False

        try:
            self._set_request_state(model, request_id, STATE_INFERENCE_ACTIVE)
            pid_observed = False
            with requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=timeout,
            ) as response:
                close_callback = response.close
                if control is not None:
                    control.cancellation.register(close_callback)
                    if control.cancellation.is_cancelled():
                        return
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if control is not None:
                        control.check()
                    if should_stop():
                        stopped = True
                        break
                    if not raw_line:
                        continue
                    item = json.loads(raw_line.decode("utf-8"))
                    final_item = item
                    chunk = item.get("message", {}).get("content", "")
                    if chunk:
                        on_token(chunk)
                        if self.owner_type != OWNER_UNKNOWN:
                            model_pid = None
                            if not pid_observed:
                                model_pid = self._observed_model_pid()
                                pid_observed = True
                            self.resource_store.heartbeat(
                                owner=self.owner_type,
                                owner_id=self.owner_id,
                                model=model,
                                state=STATE_INFERENCE_ACTIVE,
                                model_pid=model_pid,
                                request_id=request_id,
                            )
                    if item.get("done"):
                        break
                if control is not None:
                    control.cancellation.unregister(close_callback)
                done_reason = str(final_item.get("done_reason") or "").strip().lower()
                if not stopped and not final_item.get("done"):
                    raise _tag_ollama_failure(
                        IncompleteGenerationError(
                            "Ollama ended the response stream without a completion marker; "
                            "the incomplete response was rejected."
                        ),
                        stage="stream_completion",
                        classification="stream_terminated_without_completion",
                        request_sequence=request_sequence,
                        call_phase=call_phase,
                    )
                if not stopped and done_reason == "length":
                    raise _tag_ollama_failure(
                        IncompleteGenerationError(
                            "Ollama stopped at the configured output-token limit; "
                            "the incomplete response was rejected."
                        ),
                        stage="generation_length",
                        classification="output_token_limit",
                        request_sequence=request_sequence,
                        call_phase=call_phase,
                    )
        except Exception as exc:
            if not getattr(exc, "localai_failure_stage", ""):
                stage, classification = _request_failure_details(exc)
                _tag_ollama_failure(
                    exc,
                    stage=stage,
                    classification=classification,
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                )
            self._set_request_state(
                model,
                request_id,
                STATE_ERROR,
                detail=str(exc),
                observe_pid=True,
            )
            raise
        else:
            self._set_request_state(
                model,
                request_id,
                STATE_IDLE,
                observe_pid=True,
            )
            return {
                "done_reason": done_reason,
                "prompt_eval_count": final_item.get("prompt_eval_count"),
                "eval_count": final_item.get("eval_count"),
                # Native nanosecond counters let the application distinguish
                # prompt evaluation, generation, model loading and residual
                # queue/transport time without changing Ollama scheduling.
                "load_duration": final_item.get("load_duration"),
                "prompt_eval_duration": final_item.get("prompt_eval_duration"),
                "eval_duration": final_item.get("eval_duration"),
                "total_duration": final_item.get("total_duration"),
            }
