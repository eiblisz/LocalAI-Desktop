import json
import os
import uuid
from typing import Callable

import requests

from .config import OLLAMA_BASE_URL
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


class OllamaClient:
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
            return list_external_ollama_consumers(timeout=3.0)
        except Exception:
            return None

    def _observed_model_pid(self):
        processes = self._runner_processes()
        if processes is None or len(processes) != 1:
            return None
        return processes[0].get("pid")

    def _set_request_state(self, model, request_id, state, detail=""):
        if self.owner_type == OWNER_UNKNOWN:
            return None
        return self.resource_store.upsert(
            owner=self.owner_type,
            owner_id=self.owner_id,
            model=model,
            state=state,
            owner_pid=os.getpid(),
            model_pid=self._observed_model_pid(),
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

        external = self._external_consumers()
        if external is None:
            raise OllamaResourceBusyError(
                "Could not verify external Ollama consumers; model switch is blocked."
            )
        if external:
            owner = external[0].get("owner", OWNER_UNKNOWN)
            raise OllamaResourceBusyError(
                f"Ollama is in use by another local owner ({owner}); "
                "model switch is waiting rather than stopping it."
            )

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
    ) -> str:
        if self.auto_prepare_model:
            self.prepare_model(model)

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if response_format is not None:
            if not isinstance(response_format, (str, dict)):
                raise TypeError("response_format must be a string, object, or None.")
            payload["format"] = response_format

        try:
            self._set_request_state(model, request_id, STATE_INFERENCE_ACTIVE)
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            item = response.json()
            result = item.get("message", {}).get("content", "")
        except Exception as exc:
            self._set_request_state(
                model,
                request_id,
                STATE_ERROR,
                detail=str(exc),
            )
            raise
        else:
            self._set_request_state(model, request_id, STATE_IDLE)
            return result

    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        on_token: Callable[[str], None],
        should_stop: Callable[[], bool],
        timeout: float = 600.0,
    ) -> None:
        if self.auto_prepare_model:
            self.prepare_model(model)

        request_id = uuid.uuid4().hex
        self._set_request_state(model, request_id, STATE_MODEL_LOADING)
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        try:
            self._set_request_state(model, request_id, STATE_INFERENCE_ACTIVE)
            with requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if should_stop():
                        break
                    if not raw_line:
                        continue
                    item = json.loads(raw_line.decode("utf-8"))
                    chunk = item.get("message", {}).get("content", "")
                    if chunk:
                        on_token(chunk)
                        if self.owner_type != OWNER_UNKNOWN:
                            self.resource_store.heartbeat(
                                owner=self.owner_type,
                                owner_id=self.owner_id,
                                model=model,
                                state=STATE_INFERENCE_ACTIVE,
                                model_pid=self._observed_model_pid(),
                                request_id=request_id,
                            )
                    if item.get("done"):
                        break
        except Exception as exc:
            self._set_request_state(
                model,
                request_id,
                STATE_ERROR,
                detail=str(exc),
            )
            raise
        else:
            self._set_request_state(model, request_id, STATE_IDLE)
