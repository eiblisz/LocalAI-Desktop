import json

import pytest

from app.extension_store import (
    ExtensionStore,
    test_extension_connection as run_connection_test,
)


def test_extension_store_round_trip_and_private_registry_location(tmp_path):
    store = ExtensionStore(tmp_path)

    saved = store.save({
        "name": "ComfyUI",
        "type": "local_service",
        "endpoint": "http://127.0.0.1:8188",
        "enabled": True,
        "auth_type": "none",
        "capabilities": "image_generate, image_edit, image_generate",
        "timeout": 7,
    })

    assert saved["name"] == "ComfyUI"
    assert saved["enabled"] is True
    assert saved["capabilities"] == ["image_generate", "image_edit"]
    assert saved["last_status"] == "never"
    assert store.get(saved["id"])["endpoint"] == "http://127.0.0.1:8188"
    assert store.path == tmp_path / "registry.json"

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["extensions"]) == 1


def test_extension_store_updates_existing_entry_without_duplication(tmp_path):
    store = ExtensionStore(tmp_path)
    saved = store.save({
        "name": "Brave",
        "type": "http_api",
        "endpoint": "https://api.search.brave.com/res/v1/web/search",
        "enabled": False,
        "auth_type": "api_key",
        "capabilities": ["web_search"],
    })

    saved["enabled"] = True
    updated = store.save(saved)

    assert updated["id"] == saved["id"]
    assert updated["enabled"] is True
    assert len(store.list_extensions()) == 1


def test_extension_store_rejects_embedded_credentials_and_secret_config(tmp_path):
    store = ExtensionStore(tmp_path)

    with pytest.raises(ValueError, match="credentials must not be embedded"):
        store.save({
            "name": "Bad endpoint",
            "type": "http_api",
            "endpoint": "https://user:password@example.com/api",
        })

    with pytest.raises(ValueError, match="secret query parameters"):
        store.save({
            "name": "Bad query",
            "type": "http_api",
            "endpoint": "https://example.com/api?api_key=secret-value",
        })

    with pytest.raises(ValueError, match="secret config field"):
        store.save({
            "name": "Bad config",
            "type": "http_api",
            "endpoint": "https://example.com/api",
            "config": {"token": "secret-value"},
        })


def test_extension_store_delete_and_enabled_state(tmp_path):
    store = ExtensionStore(tmp_path)
    saved = store.save({
        "name": "Local service",
        "type": "local_service",
        "endpoint": "http://127.0.0.1:9999",
    })

    enabled = store.set_enabled(saved["id"], True)
    assert enabled["enabled"] is True

    store.delete(saved["id"])
    assert store.list_extensions() == []

    with pytest.raises(KeyError):
        store.get(saved["id"])


def test_connection_test_accepts_reachable_and_auth_required_services():
    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    calls = []

    def reachable(url, timeout, allow_redirects):
        calls.append((url, timeout, allow_redirects))
        return Response(200)

    result = run_connection_test({
        "type": "local_service",
        "endpoint": "http://127.0.0.1:8188",
        "timeout": 4,
    }, requester=reachable)

    assert result == {
        "status": "connected",
        "ok": True,
        "message": "Reachable (HTTP 200).",
    }
    assert calls == [("http://127.0.0.1:8188", 4.0, True)]

    auth = run_connection_test({
        "type": "http_api",
        "endpoint": "https://example.com/api",
    }, requester=lambda *_args, **_kwargs: Response(401))

    assert auth["status"] == "auth_required"
    assert auth["ok"] is True


def test_connection_test_fails_closed_for_unimplemented_extension_types():
    result = run_connection_test({
        "type": "mcp_connector",
        "endpoint": "http://127.0.0.1:3000",
    })

    assert result["status"] == "unsupported"
    assert result["ok"] is False


def test_test_result_is_persisted_without_changing_extension_definition(tmp_path):
    store = ExtensionStore(tmp_path)
    saved = store.save({
        "name": "ComfyUI",
        "type": "local_service",
        "endpoint": "http://127.0.0.1:8188",
        "enabled": True,
        "capabilities": ["image_generate"],
    })

    updated = store.record_test_result(
        saved["id"],
        "connected",
        "Reachable (HTTP 200).",
    )

    assert updated["last_status"] == "connected"
    assert updated["last_tested"]
    assert updated["endpoint"] == saved["endpoint"]
    assert updated["capabilities"] == ["image_generate"]


def test_store_can_find_installed_catalog_preset(tmp_path):
    store = ExtensionStore(tmp_path)
    saved = store.save({
        "name": "GitHub",
        "type": "mcp_connector",
        "endpoint": "",
        "enabled": False,
        "auth_type": "oauth",
        "capabilities": ["repo_read"],
        "config": {
            "preset_id": "github",
            "category": "Developer Tools",
        },
    })

    found = store.find_by_preset_id("github")
    assert found is not None
    assert found["id"] == saved["id"]
    assert store.find_by_preset_id("missing") is None


def test_secret_url_auth_stores_reference_not_secret_value(tmp_path):
    store = ExtensionStore(tmp_path)
    saved = store.save({
        "name": "Discord Webhook",
        "type": "http_api",
        "endpoint": "",
        "enabled": False,
        "auth_type": "secret_url",
        "credential_ref": "extension:abc:discord_webhook_url",
        "capabilities": ["send_message", "send_embed"],
        "config": {"preset_id": "discord-webhook"},
    })

    assert saved["auth_type"] == "secret_url"
    assert saved["credential_ref"] == "extension:abc:discord_webhook_url"

    raw = store.path.read_text(encoding="utf-8")
    assert "discord.com/api/webhooks/" not in raw
    assert "token-value" not in raw

