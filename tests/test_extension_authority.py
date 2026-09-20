from app.extension_authority import (
    PERMISSION_EXTERNAL_READ,
    PERMISSION_EXTERNAL_WRITE,
    PERMISSION_REMOTE_INTERFACE,
    ExtensionAuthority,
    ExtensionExecutionContext,
    permission_for_capability,
)


class Store:
    def __init__(self, extension):
        self.extension = extension

    def find_by_preset_id(self, preset_id):
        if self.extension is None:
            return None
        config = self.extension.get("config") or {}
        return self.extension if config.get("preset_id") == preset_id else None


def _extension(*, enabled=True, capabilities=None, preset_id="crypto-market-data"):
    return {
        "id": "ext-1",
        "name": "Test extension",
        "enabled": enabled,
        "capabilities": capabilities or ["crypto_quote"],
        "config": {"preset_id": preset_id},
    }


def test_desktop_chat_requires_attachment_and_read_permission():
    authority = ExtensionAuthority(Store(_extension()))
    denied = authority.authorize_preset(
        "crypto-market-data",
        "crypto_quote",
        ExtensionExecutionContext.desktop_chat([]),
    )
    allowed = authority.authorize_preset(
        "crypto-market-data",
        "crypto_quote",
        ExtensionExecutionContext.desktop_chat(["ext-1"]),
    )

    assert denied.allowed is False
    assert "not attached" in denied.reason
    assert denied.required_permission == PERMISSION_EXTERNAL_READ
    assert allowed.allowed is True
    assert allowed.extension["id"] == "ext-1"


def test_disabled_extension_is_never_execution_authority():
    authority = ExtensionAuthority(Store(_extension(enabled=False)))

    decision = authority.authorize_preset(
        "crypto-market-data",
        "crypto_quote",
        ExtensionExecutionContext.desktop_chat(["ext-1"]),
    )

    assert decision.allowed is False
    assert decision.reason == "extension is disabled"


def test_extension_must_declare_requested_capability():
    authority = ExtensionAuthority(
        Store(_extension(capabilities=["crypto_ticker"]))
    )

    decision = authority.authorize_preset(
        "crypto-market-data",
        "crypto_quote",
        ExtensionExecutionContext.desktop_chat(["ext-1"]),
    )

    assert decision.allowed is False
    assert "does not declare capability" in decision.reason


def test_desktop_chat_does_not_grant_external_write():
    extension = _extension(
        capabilities=["calendar_write"],
        preset_id="calendar",
    )
    authority = ExtensionAuthority(Store(extension))

    decision = authority.authorize_preset(
        "calendar",
        "calendar_write",
        ExtensionExecutionContext.desktop_chat(["ext-1"]),
    )

    assert permission_for_capability("calendar_write") == PERMISSION_EXTERNAL_WRITE
    assert decision.allowed is False
    assert "does not grant permission" in decision.reason


def test_discord_remote_can_use_enabled_read_only_market_extension_without_chat_attachment():
    authority = ExtensionAuthority(Store(_extension()))

    decision = authority.authorize_preset(
        "crypto-market-data",
        "crypto_quote",
        ExtensionExecutionContext.discord_remote(),
    )

    assert decision.allowed is True
    assert decision.scope == "discord_remote"


def test_background_service_authorizes_only_remote_interface_capability():
    extension = _extension(
        capabilities=["remote_chat", "send_message"],
        preset_id="discord-bot",
    )
    authority = ExtensionAuthority(Store(extension))
    context = ExtensionExecutionContext.background_service()

    remote = authority.authorize_preset(
        "discord-bot",
        "remote_chat",
        context,
    )
    send = authority.authorize_preset(
        "discord-bot",
        "send_message",
        context,
    )

    assert remote.allowed is True
    assert remote.required_permission == PERMISSION_REMOTE_INTERFACE
    assert send.allowed is False


def test_unknown_capability_fails_closed_without_generic_execution_permission():
    extension = _extension(
        capabilities=["dangerous_custom_action"],
        preset_id="custom",
    )
    authority = ExtensionAuthority(Store(extension))

    decision = authority.authorize_preset(
        "custom",
        "dangerous_custom_action",
        ExtensionExecutionContext.desktop_workspace(),
    )

    assert decision.allowed is False
    assert "does not grant permission" in decision.reason
