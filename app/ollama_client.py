import json
import os
import threading
import time
import uuid
from math import ceil
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


# Ollama's default runner window is 4096 tokens.  We only request a larger
# window when the final, already-assembled chat payload needs it.  The steps
# avoid an unnecessarily large KV cache while still giving a loaded model one
# predictable next size when grounded context would otherwise overflow.
_DEFAULT_NUM_CTX = 4096
_CONTEXT_SAFETY_FLOOR = 192
_CONTEXT_SAFETY_MAX = 512
_MESSAGE_TEMPLATE_OVERHEAD = 16
_IMAGE_CONTEXT_ALLOWANCE = 256
_MODEL_WARMUP_KEEP_ALIVE = "5m"
_MODEL_WARMUP_POLL_ATTEMPTS = 4
_MODEL_WARMUP_POLL_DELAY = 0.15


class IncompleteGenerationError(RuntimeError):
    pass


def _positive_int(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _text_token_estimate(value):
    """Stable, conservative local estimate; this is not a tokenizer contract."""
    text = str(value or "")
    return max(1, ceil(len(text) / 4)) if text else 0


def _final_message_token_estimate(messages):
    """Estimate the final API payload, including role/template overhead.

    This intentionally runs at the Ollama boundary, after workers have added
    evidence, grounded system instructions, and conversation messages.  Image
    bytes are not text tokens, but a bounded per-image allowance preserves a
    safety margin for multimodal templates without serializing image data.
    """
    total = 0
    for message in list(messages or []):
        if not isinstance(message, dict):
            total += _text_token_estimate(message) + _MESSAGE_TEMPLATE_OVERHEAD
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            total += _text_token_estimate(content)
        elif content:
            try:
                total += _text_token_estimate(
                    json.dumps(content, ensure_ascii=False, sort_keys=True)
                )
            except (TypeError, ValueError):
                total += _text_token_estimate(content)
        total += _MESSAGE_TEMPLATE_OVERHEAD
        images = message.get("images") or []
        if isinstance(images, (list, tuple)):
            total += _IMAGE_CONTEXT_ALLOWANCE * len(images)
    return total


def _context_length_from_show_payload(payload):
    """Extract a model-declared context maximum without model-name rules."""
    if not isinstance(payload, dict):
        return None
    candidates = []
    pending = [payload]
    while pending:
        current = pending.pop()
        if not isinstance(current, dict):
            continue
        for key, value in current.items():
            normalized = str(key or "").strip().lower().replace("-", "_")
            if normalized.endswith("context_length") or normalized in {
                "context_length",
                "context_window",
                "num_ctx",
            }:
                parsed = _positive_int(value)
                if parsed:
                    candidates.append(parsed)
            elif isinstance(value, dict):
                pending.append(value)
    return max(candidates) if candidates else None


def _ollama_http_error_detail(response, limit=500):
    """Return only Ollama's bounded error message, never the request payload."""
    if response is None:
        return ""
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("error", "detail", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    detail = value.strip()
                    break
    except Exception:
        detail = ""
    if not detail:
        try:
            detail = str(getattr(response, "text", "") or "").strip()
        except Exception:
            detail = ""
    detail = " ".join(detail.split())
    if len(detail) > int(limit):
        detail = detail[: int(limit) - 3].rstrip() + "..."
    return detail


def _tag_ollama_failure(
    exc,
    *,
    stage,
    classification,
    request_sequence=None,
    call_phase=None,
    preparation_reason=None,
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
        if preparation_reason:
            detail = " ".join(str(preparation_reason).split())
            exc.localai_ollama_preparation_reason = detail[:500]
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            exc.localai_ollama_http_status = int(status)
        http_detail = _ollama_http_error_detail(response)
        if http_detail:
            exc.localai_ollama_http_detail = http_detail
    except Exception:
        pass
    return exc


def _context_budget_metadata(
    *,
    estimated_prompt_tokens,
    output_tokens,
    requested_num_ctx,
    model_max_context,
    decision,
    safety_tokens,
):
    metadata = {
        # RequestTrace deliberately excludes metadata keys containing "token"
        # so these use its established "units" naming while UI labels remain
        # explicit about their token-estimate meaning.
        "estimated_final_prompt_units": int(estimated_prompt_tokens),
        "requested_output_units": int(output_tokens),
        "requested_num_ctx": int(requested_num_ctx),
        "context_budget_decision": str(decision or ""),
        "context_budget_safety_units": int(safety_tokens),
    }
    if model_max_context:
        metadata["model_max_context"] = int(model_max_context)
    return metadata


def _tag_context_budget(exc, metadata):
    """Preserve the exact context decision on a later Ollama failure."""
    try:
        for key, value in dict(metadata or {}).items():
            setattr(exc, f"localai_{key}", value)
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
        ("localai_ollama_http_detail", "ollama_http_detail"),
        ("localai_ollama_call_phase", "ollama_call_phase"),
        ("localai_ollama_preparation_reason", "ollama_preparation_reason"),
        ("localai_estimated_final_prompt_units", "estimated_final_prompt_units"),
        ("localai_requested_output_units", "requested_output_units"),
        ("localai_requested_num_ctx", "requested_num_ctx"),
        ("localai_model_max_context", "model_max_context"),
        ("localai_context_budget_decision", "context_budget_decision"),
        ("localai_context_budget_safety_units", "context_budget_safety_units"),
        ("localai_model_resident_before", "model_resident_before"),
        ("localai_model_warmup_required", "model_warmup_required"),
        ("localai_model_warmup_reason", "model_warmup_reason"),
        ("localai_model_warmup_result", "model_warmup_result"),
        ("localai_model_resident_after", "model_resident_after"),
        (
            "localai_model_warmup_requested_num_ctx",
            "model_warmup_requested_num_ctx",
        ),
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
        self._model_context_lock = threading.Lock()
        # ``/api/show`` is static model metadata. Cache known limits for this
        # client lifetime; a transient metadata failure remains retryable.
        self._model_context_max_cache = {}
        # Best-effort client-local record of context windows that were
        # explicitly preflighted or completed successfully. Presence is still
        # re-checked through /api/ps before trusting this cache.
        self._prepared_runtime_context = {}

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

    def _model_max_context(self, model):
        """Return the declared context maximum from cached Ollama metadata."""
        key = str(model or "").strip().casefold()
        if not key:
            return None
        with self._model_context_lock:
            if key in self._model_context_max_cache:
                return self._model_context_max_cache[key]
        maximum = None
        try:
            response = requests.post(
                f"{self.base_url}/api/show",
                json={"model": str(model).strip()},
                timeout=5.0,
            )
            response.raise_for_status()
            maximum = _context_length_from_show_payload(response.json())
        except (requests.RequestException, TypeError, ValueError, AttributeError):
            maximum = None
        if maximum is not None:
            with self._model_context_lock:
                self._model_context_max_cache[key] = maximum
        return maximum

    def _context_budget(self, model, messages, output_budget):
        """Choose the smallest safe Ollama context for the final chat payload."""
        prompt_tokens = _final_message_token_estimate(messages)
        safety_tokens = max(
            _CONTEXT_SAFETY_FLOOR,
            min(
                _CONTEXT_SAFETY_MAX,
                ceil((prompt_tokens + int(output_budget)) * 0.07),
            ),
        )
        required_tokens = prompt_tokens + int(output_budget) + safety_tokens
        if required_tokens <= _DEFAULT_NUM_CTX:
            # Do not send num_ctx when the request already fits the runner's
            # ordinary 4096-token window. This preserves the resident model's
            # existing context and avoids an unnecessary configuration change.
            return (
                _context_budget_metadata(
                    estimated_prompt_tokens=prompt_tokens,
                    output_tokens=output_budget,
                    requested_num_ctx=_DEFAULT_NUM_CTX,
                    model_max_context=None,
                    decision="fits_default_context",
                    safety_tokens=safety_tokens,
                ),
                False,
            )

        model_max_context = self._model_max_context(model)
        if model_max_context is None:
            # Without a declared bound, preserve the current safe default. A
            # speculative larger KV cache could exceed an unknown model limit.
            requested_num_ctx = _DEFAULT_NUM_CTX
            decision = "model_max_context_unavailable_preserved_default"
        else:
            requested_num_ctx = _DEFAULT_NUM_CTX
            while (
                requested_num_ctx < required_tokens
                and requested_num_ctx < model_max_context
            ):
                requested_num_ctx *= 2
            requested_num_ctx = min(requested_num_ctx, model_max_context)
            decision = (
                "raised_to_next_context_step"
                if requested_num_ctx >= required_tokens
                else "model_max_context_insufficient"
            )

        return (
            _context_budget_metadata(
                estimated_prompt_tokens=prompt_tokens,
                output_tokens=output_budget,
                requested_num_ctx=requested_num_ctx,
                model_max_context=model_max_context,
                decision=decision,
                safety_tokens=safety_tokens,
            ),
            requested_num_ctx != _DEFAULT_NUM_CTX,
        )

    @staticmethod
    def _notify_context_budget(callback, metadata):
        if callback is None:
            return
        try:
            callback(dict(metadata or {}))
        except Exception:
            # Diagnostics must never block a local inference request.
            pass

    def _remember_prepared_context(self, model, num_ctx):
        key = str(model or "").strip().casefold()
        value = _positive_int(num_ctx)
        if not key or not value:
            return
        with self._model_context_lock:
            previous = _positive_int(self._prepared_runtime_context.get(key)) or 0
            self._prepared_runtime_context[key] = max(previous, value)

    def _known_prepared_context(self, model):
        key = str(model or "").strip().casefold()
        if not key:
            return None
        with self._model_context_lock:
            return _positive_int(self._prepared_runtime_context.get(key))

    def _ensure_model_ready(
        self,
        model,
        *,
        requested_num_ctx,
        apply_num_ctx,
        timeout,
    ):
        """Preflight a cold/context-changing runner before user generation.

        Ollama normally loads models lazily on the first generation request.
        On some model/template combinations that makes the user's first
        /api/chat call double as the runner load/context-resize transition.
        A load-only /api/generate request makes that transition explicit and
        keeps the real user request on an already-ready runner.

        This never sends keep_alive=0, never kills a process, and never calls
        the host's unload path. Ollama remains responsible for its own normal
        residency decisions.
        """
        target = str(model or "").strip()
        metadata = {
            "model_resident_before": False,
            "model_warmup_required": False,
            "model_warmup_reason": "",
            "model_warmup_result": "not_needed",
            "model_resident_after": False,
            "model_warmup_requested_num_ctx": int(requested_num_ctx),
        }
        loaded_before = loaded_ollama_models(
            self,
            timeout=min(max(float(timeout), 1.0), 2.5),
        )
        resident_before = target in loaded_before
        metadata["model_resident_before"] = bool(resident_before)

        known_context = self._known_prepared_context(target)
        context_preflight_needed = bool(
            apply_num_ctx
            and (
                known_context is None
                or int(known_context) < int(requested_num_ctx)
            )
        )
        warmup_required = (not resident_before) or context_preflight_needed
        metadata["model_warmup_required"] = bool(warmup_required)
        if not warmup_required:
            metadata["model_resident_after"] = True
            return metadata

        metadata["model_warmup_reason"] = (
            "cold_model"
            if not resident_before
            else "context_preflight"
        )
        payload = {
            "model": target,
            "prompt": "",
            "stream": False,
            "keep_alive": _MODEL_WARMUP_KEEP_ALIVE,
        }
        if apply_num_ctx:
            payload["options"] = {"num_ctx": int(requested_num_ctx)}

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=min(max(float(timeout), 10.0), 120.0),
        )
        response.raise_for_status()
        self._remember_prepared_context(target, requested_num_ctx)

        resident_after = False
        for attempt in range(_MODEL_WARMUP_POLL_ATTEMPTS):
            try:
                resident_after = target in loaded_ollama_models(
                    self,
                    timeout=min(max(float(timeout), 1.0), 2.5),
                )
            except requests.RequestException:
                resident_after = False
            if resident_after:
                break
            if attempt + 1 < _MODEL_WARMUP_POLL_ATTEMPTS:
                time.sleep(_MODEL_WARMUP_POLL_DELAY)

        metadata["model_resident_after"] = bool(resident_after)
        metadata["model_warmup_result"] = (
            "ready" if resident_after else "submitted_unconfirmed"
        )
        return metadata

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

    def prepare_model(
        self,
        model: str,
        timeout: float = 6.0,
        *,
        allow_model_release: bool = True,
    ) -> list[str]:
        """
        Gracefully unload only a provably self-owned idle stale model.

        A resident target and an empty resident set require no destructive
        switch, so ordinary inference may continue without consulting external
        consumer ownership. Unknown or foreign ownership is fail-closed only
        before unloading a different resident model. This method never kills a
        runner or restarts the shared Ollama server.
        """
        target = str(model or "").strip()
        if not target:
            raise ValueError("A target Ollama model is required.")

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

        # The selected model is already resident. Calling /api/chat uses that
        # model directly and does not unload, switch, kill, or restart shared
        # state. In particular, stale leases or an unrelated visible consumer
        # must not turn this no-op into a preparation failure.
        if target in loaded:
            return []

        stale = [name for name in loaded if name and name != target]
        if not stale:
            return []

        # Sending an ordinary Desktop/Discord request must never become an
        # implicit model-unload operation. Ollama can load the requested target
        # itself; explicit VRAM release retains the stricter ownership path.
        if not allow_model_release:
            return []

        # Only a real resident-model replacement can be destructive. Check
        # visible consumers immediately before any ownership-based unload.
        self._assert_external_switch_safe(target)

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
        context_budget_callback=None,
    ) -> str:
        call_phase = str(call_phase or "model_inference")
        request_sequence = self._next_request_sequence()
        if control is not None:
            control.claim_model_call()
            timeout = control.request_timeout(timeout)

        output_budget = (
            OLLAMA_NUM_PREDICT
            if num_predict is None
            else max(1, int(num_predict))
        )
        context_budget, apply_num_ctx = self._context_budget(
            model,
            messages,
            output_budget,
        )
        if self.auto_prepare_model:
            try:
                self.prepare_model(model, allow_model_release=False)
                preparation_stage = "model_warmup"
                preparation_stage = "model_warmup"
                readiness = self._ensure_model_ready(
                    model,
                    requested_num_ctx=context_budget["requested_num_ctx"],
                    apply_num_ctx=apply_num_ctx,
                    timeout=timeout,
                )
                context_budget.update(readiness)
            except Exception as exc:
                self._notify_context_budget(
                    context_budget_callback,
                    context_budget,
                )
                _tag_context_budget(exc, context_budget)
                raise _tag_ollama_failure(
                    exc,
                    stage="model_preparation",
                    classification=(
                        "model_warmup_failed"
                        if locals().get("preparation_stage") == "model_warmup"
                        else "model_prepare_failed"
                    ),
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                    preparation_reason=exc,
                )
        self._notify_context_budget(context_budget_callback, context_budget)

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        structured_response = response_format is not None
        options = {"num_predict": output_budget}
        if apply_num_ctx:
            options["num_ctx"] = context_budget["requested_num_ctx"]
        payload = {
            "model": model,
            "messages": messages,
            # Keep controlled helper calls on the same streaming transport as
            # ordinary generation. Some Ollama/model combinations return HTTP
            # 500 for non-streaming structured requests. If a structured stream
            # closes after emitting complete JSON but before the terminal done
            # marker, the JSON contract below can safely accept that content;
            # the caller still performs its stricter semantic validation.
            "stream": bool(control is not None),
            "options": options,
        }
        # The think parameter is not accepted by every model template. Some
        # ordinary models reject even an explicit false value with HTTP 400.
        # Only send it when the operator deliberately enables thinking.
        if OLLAMA_THINKING_ENABLED:
            payload["think"] = True
        if response_format is not None:
            if not isinstance(response_format, (str, dict)):
                raise TypeError("response_format must be a string, object, or None.")
            payload["format"] = response_format

        try:
            self._set_request_state(model, request_id, STATE_INFERENCE_ACTIVE)
            if control is None:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
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
                    structured_json_complete = False
                    if structured_response and result.strip():
                        try:
                            json.loads(result)
                            structured_json_complete = True
                        except (TypeError, ValueError, json.JSONDecodeError):
                            structured_json_complete = False
                    if not structured_json_complete:
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
            _tag_context_budget(exc, context_budget)
            self._set_request_state(
                model,
                request_id,
                STATE_ERROR,
                detail=str(exc),
                observe_pid=True,
            )
            raise
        else:
            self._remember_prepared_context(
                model,
                context_budget["requested_num_ctx"],
            )
            self._remember_prepared_context(
                model,
                context_budget["requested_num_ctx"],
            )
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
        context_budget_callback=None,
    ) -> None:
        call_phase = str(call_phase or "model_inference")
        request_sequence = self._next_request_sequence()
        if control is not None:
            control.claim_model_call()
            timeout = control.request_timeout(timeout)

        output_budget = (
            OLLAMA_NUM_PREDICT
            if num_predict is None
            else max(1, int(num_predict))
        )
        context_budget, apply_num_ctx = self._context_budget(
            model,
            messages,
            output_budget,
        )
        if self.auto_prepare_model:
            try:
                self.prepare_model(model, allow_model_release=False)
                readiness = self._ensure_model_ready(
                    model,
                    requested_num_ctx=context_budget["requested_num_ctx"],
                    apply_num_ctx=apply_num_ctx,
                    timeout=timeout,
                )
                context_budget.update(readiness)
            except Exception as exc:
                self._notify_context_budget(
                    context_budget_callback,
                    context_budget,
                )
                _tag_context_budget(exc, context_budget)
                raise _tag_ollama_failure(
                    exc,
                    stage="model_preparation",
                    classification=(
                        "model_warmup_failed"
                        if locals().get("preparation_stage") == "model_warmup"
                        else "model_prepare_failed"
                    ),
                    request_sequence=request_sequence,
                    call_phase=call_phase,
                    preparation_reason=exc,
                )
        self._notify_context_budget(context_budget_callback, context_budget)

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        options = {"num_predict": output_budget}
        if apply_num_ctx:
            options["num_ctx"] = context_budget["requested_num_ctx"]
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": options,
        }
        if OLLAMA_THINKING_ENABLED:
            payload["think"] = True
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
            _tag_context_budget(exc, context_budget)
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
                "context_budget": context_budget,
            }
