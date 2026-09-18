import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import requests

from .config import EXTENSIONS_DIR


REGISTRY_VERSION = 1

EXTENSION_TYPES = {
    "http_api": "HTTP API",
    "local_service": "LOCAL SERVICE",
    "mcp_connector": "MCP / CONNECTOR",
    "custom_tool": "CUSTOM TOOL",
}

AUTH_TYPES = {
    "none": "None",
    "api_key": "API Key",
    "bearer": "Bearer Token",
    "basic": "Basic Auth",
    "oauth": "OAuth",
}

_SECRET_TOKENS = {
    "api_key",
    "apikey",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "client_secret",
    "authorization",
    "cookie",
    "session",
}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _clean(value):
    return " ".join(str(value or "").strip().split())


def _normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "_", _clean(value).lower()).strip("_")


def _contains_secret_key(value):
    normalized = _normalize_key(value)
    if normalized in _SECRET_TOKENS:
        return True
    parts = set(normalized.split("_"))
    return any(token in parts for token in _SECRET_TOKENS)


def _validate_public_endpoint(endpoint):
    endpoint = _clean(endpoint)
    if not endpoint:
        return endpoint

    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint must use http:// or https://")
    if not parsed.hostname:
        raise ValueError("endpoint must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in extension endpoints")

    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if _contains_secret_key(key):
            raise ValueError(
                "secret query parameters must not be stored in the extension registry"
            )
    return endpoint


def _validate_public_config(config):
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise TypeError("config must be an object")

    clean = {}
    for key, value in config.items():
        clean_key = _clean(key)
        if not clean_key:
            continue
        if _contains_secret_key(clean_key):
            raise ValueError(
                f"secret config field is not allowed in registry: {clean_key}"
            )
        if isinstance(value, dict):
            clean[clean_key] = _validate_public_config(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[clean_key] = value
        else:
            raise TypeError(
                f"unsupported config value type for {clean_key}: {type(value).__name__}"
            )
    return clean


def _normalize_capabilities(values):
    if isinstance(values, str):
        values = values.split(",")

    result = []
    for value in values or []:
        item = _normalize_key(value)
        if item and item not in result:
            result.append(item)
    return result


def _default_registry():
    return {
        "version": REGISTRY_VERSION,
        "extensions": [],
    }


class ExtensionStore:
    def __init__(self, root: Path = EXTENSIONS_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_root = self.root / "configs"
        self.config_root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"

    def _read(self):
        if not self.path.exists():
            return _default_registry()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"extension registry is unreadable: {exc}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("extension registry root must be an object")
        if payload.get("version") != REGISTRY_VERSION:
            raise RuntimeError(
                f"unsupported extension registry version: {payload.get('version')}"
            )
        extensions = payload.get("extensions")
        if not isinstance(extensions, list):
            raise RuntimeError("extension registry extensions must be a list")
        return payload

    def _write(self, payload):
        self.root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

        fd, temp_name = tempfile.mkstemp(
            prefix="registry-",
            suffix=".tmp",
            dir=str(self.root),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass

    @staticmethod
    def _normalize(extension, *, existing=None):
        extension = dict(extension or {})
        existing = dict(existing or {})

        extension_id = _clean(extension.get("id") or existing.get("id"))
        if not extension_id:
            extension_id = uuid.uuid4().hex

        name = _clean(extension.get("name"))
        if not name:
            raise ValueError("extension name is required")

        extension_type = _normalize_key(
            extension.get("type") or existing.get("type") or "http_api"
        )
        if extension_type not in EXTENSION_TYPES:
            raise ValueError(f"unsupported extension type: {extension_type}")

        auth_type = _normalize_key(
            extension.get("auth_type") or existing.get("auth_type") or "none"
        )
        if auth_type not in AUTH_TYPES:
            raise ValueError(f"unsupported auth type: {auth_type}")

        endpoint = _validate_public_endpoint(extension.get("endpoint", ""))
        capabilities = _normalize_capabilities(
            extension.get("capabilities", existing.get("capabilities", []))
        )
        config = _validate_public_config(
            extension.get("config", existing.get("config", {}))
        )

        try:
            timeout = float(extension.get("timeout", existing.get("timeout", 10.0)))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout must be numeric") from exc
        if timeout < 1.0 or timeout > 120.0:
            raise ValueError("timeout must be between 1 and 120 seconds")

        created_at = existing.get("created_at") or _now()

        return {
            "id": extension_id,
            "name": name,
            "type": extension_type,
            "endpoint": endpoint,
            "enabled": bool(extension.get("enabled", existing.get("enabled", False))),
            "auth_type": auth_type,
            "credential_ref": _clean(
                extension.get("credential_ref", existing.get("credential_ref", ""))
            ),
            "capabilities": capabilities,
            "timeout": timeout,
            "config": config,
            "last_tested": existing.get("last_tested"),
            "last_status": existing.get("last_status", "never"),
            "last_message": existing.get("last_message", ""),
            "created_at": created_at,
            "updated_at": _now(),
        }

    def list_extensions(self):
        payload = self._read()
        return sorted(
            [dict(item) for item in payload["extensions"]],
            key=lambda item: (
                not bool(item.get("enabled", False)),
                str(item.get("name", "")).casefold(),
            ),
        )

    def get(self, extension_id):
        extension_id = _clean(extension_id)
        for item in self._read()["extensions"]:
            if item.get("id") == extension_id:
                return dict(item)
        raise KeyError(extension_id)

    def find_by_preset_id(self, preset_id):
        preset_id = _clean(preset_id)
        if not preset_id:
            return None
        for item in self._read()["extensions"]:
            config = item.get("config") or {}
            if _clean(config.get("preset_id")) == preset_id:
                return dict(item)
        return None

    def save(self, extension):
        payload = self._read()
        extension = dict(extension or {})
        extension_id = _clean(extension.get("id"))

        existing = None
        existing_index = None
        if extension_id:
            for index, item in enumerate(payload["extensions"]):
                if item.get("id") == extension_id:
                    existing = item
                    existing_index = index
                    break

        normalized = self._normalize(extension, existing=existing)
        if existing_index is None:
            payload["extensions"].append(normalized)
        else:
            payload["extensions"][existing_index] = normalized

        self._write(payload)
        return dict(normalized)

    def delete(self, extension_id):
        payload = self._read()
        extension_id = _clean(extension_id)
        before = len(payload["extensions"])
        payload["extensions"] = [
            item
            for item in payload["extensions"]
            if item.get("id") != extension_id
        ]
        if len(payload["extensions"]) == before:
            raise KeyError(extension_id)
        self._write(payload)

    def set_enabled(self, extension_id, enabled):
        item = self.get(extension_id)
        item["enabled"] = bool(enabled)
        return self.save(item)

    def record_test_result(self, extension_id, status, message):
        payload = self._read()
        extension_id = _clean(extension_id)
        for index, item in enumerate(payload["extensions"]):
            if item.get("id") != extension_id:
                continue
            updated = dict(item)
            updated["last_tested"] = _now()
            updated["last_status"] = _clean(status) or "error"
            updated["last_message"] = _clean(message)[:500]
            updated["updated_at"] = _now()
            payload["extensions"][index] = updated
            self._write(payload)
            return dict(updated)
        raise KeyError(extension_id)


def test_extension_connection(extension, requester=requests.get):
    extension = dict(extension or {})
    extension_type = _normalize_key(extension.get("type"))
    endpoint = _validate_public_endpoint(extension.get("endpoint", ""))

    if extension_type not in {"http_api", "local_service"}:
        return {
            "status": "unsupported",
            "ok": False,
            "message": "Connection testing is not implemented for this extension type yet.",
        }

    if not endpoint:
        return {
            "status": "error",
            "ok": False,
            "message": "Endpoint is required before testing this extension.",
        }

    timeout = float(extension.get("timeout", 10.0) or 10.0)
    try:
        response = requester(endpoint, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return {
            "status": "error",
            "ok": False,
            "message": f"Connection failed: {exc}",
        }

    status_code = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status_code < 400:
        return {
            "status": "connected",
            "ok": True,
            "message": f"Reachable (HTTP {status_code}).",
        }
    if status_code in {401, 403}:
        return {
            "status": "auth_required",
            "ok": True,
            "message": f"Service is reachable but requires authentication (HTTP {status_code}).",
        }
    return {
        "status": "error",
        "ok": False,
        "message": f"Service responded with HTTP {status_code or 'unknown'}.",
    }
