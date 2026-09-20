from dataclasses import dataclass


PERMISSION_EXTERNAL_READ = "external_read"
PERMISSION_EXTERNAL_WRITE = "external_write"
PERMISSION_LOCAL_EXECUTE = "local_execute"
PERMISSION_REMOTE_INTERFACE = "remote_interface"
PERMISSION_WORKSPACE_OPEN = "workspace_open"
PERMISSION_EXTENSION_EXECUTE = "extension_execute"


_WORKSPACE_CAPABILITIES = {
    "market_chart",
    "market_visualization",
    "stocks",
    "crypto",
    "forex",
    "indices",
}

_REMOTE_INTERFACE_CAPABILITIES = {
    "remote_chat",
}

_LOCAL_EXECUTE_CAPABILITIES = {
    "image_generate",
    "image_edit",
}

_EXTERNAL_READ_CAPABILITIES = {
    "crypto_quote",
    "crypto_ticker",
    "crypto_24h",
    "market_quote",
    "stock_quote",
    "forex_quote",
    "index_quote",
    "web_research",
    "read_messages",
}

_EXTERNAL_WRITE_CAPABILITIES = {
    "send_message",
    "send_embed",
    "file_upload",
}


def permission_for_capability(capability):
    capability = str(capability or "").strip().lower()
    if not capability:
        return PERMISSION_EXTENSION_EXECUTE

    if capability in _WORKSPACE_CAPABILITIES:
        return PERMISSION_WORKSPACE_OPEN
    if capability in _REMOTE_INTERFACE_CAPABILITIES:
        return PERMISSION_REMOTE_INTERFACE
    if capability in _LOCAL_EXECUTE_CAPABILITIES:
        return PERMISSION_LOCAL_EXECUTE
    if capability in _EXTERNAL_READ_CAPABILITIES:
        return PERMISSION_EXTERNAL_READ
    if capability in _EXTERNAL_WRITE_CAPABILITIES:
        return PERMISSION_EXTERNAL_WRITE

    if capability.endswith("_read"):
        return PERMISSION_EXTERNAL_READ
    if capability.endswith("_write"):
        return PERMISSION_EXTERNAL_WRITE
    if capability.endswith("_quote") or capability.endswith("_ticker"):
        return PERMISSION_EXTERNAL_READ

    return PERMISSION_EXTENSION_EXECUTE


@dataclass(frozen=True)
class ExtensionExecutionContext:
    scope: str
    granted_permissions: tuple[str, ...]
    attached_extension_ids: tuple[str, ...] = ()
    require_attachment: bool = False

    @classmethod
    def desktop_chat(cls, attached_extension_ids=()):
        return cls(
            scope="desktop_chat",
            granted_permissions=(PERMISSION_EXTERNAL_READ,),
            attached_extension_ids=tuple(
                str(item) for item in (attached_extension_ids or ())
            ),
            require_attachment=True,
        )

    @classmethod
    def desktop_workspace(cls):
        return cls(
            scope="desktop_workspace",
            granted_permissions=(PERMISSION_WORKSPACE_OPEN,),
            require_attachment=False,
        )

    @classmethod
    def discord_remote(cls):
        return cls(
            scope="discord_remote",
            granted_permissions=(PERMISSION_EXTERNAL_READ,),
            require_attachment=False,
        )

    @classmethod
    def background_service(cls):
        return cls(
            scope="background_service",
            granted_permissions=(PERMISSION_REMOTE_INTERFACE,),
            require_attachment=False,
        )


@dataclass(frozen=True)
class ExtensionAuthorityDecision:
    allowed: bool
    reason: str
    capability: str
    required_permission: str
    scope: str
    extension: dict | None = None


class ExtensionAuthority:
    """
    Host-owned execution authority for installed extensions.

    Registry metadata declares what an extension *can* do. The execution
    context declares what the host permits in the current scope. For Desktop
    chat execution, the extension must additionally be attached to that chat.
    """

    def __init__(self, extension_store):
        self.extension_store = extension_store

    def authorize_extension(self, extension, capability, context):
        capability = str(capability or "").strip().lower()
        extension = dict(extension or {})
        extension_id = str(extension.get("id") or "").strip()
        required_permission = permission_for_capability(capability)

        def deny(reason):
            return ExtensionAuthorityDecision(
                allowed=False,
                reason=reason,
                capability=capability,
                required_permission=required_permission,
                scope=context.scope,
                extension=None,
            )

        if not extension_id:
            return deny("extension is not installed")
        if not bool(extension.get("enabled", False)):
            return deny("extension is disabled")

        capabilities = {
            str(item or "").strip().lower()
            for item in (extension.get("capabilities") or [])
            if str(item or "").strip()
        }
        if capability not in capabilities:
            return deny(
                f"extension does not declare capability: {capability}"
            )

        permissions = {
            str(item or "").strip().lower()
            for item in context.granted_permissions
        }
        if required_permission not in permissions:
            return deny(
                f"host scope does not grant permission: {required_permission}"
            )

        if context.require_attachment:
            attached = {
                str(item or "").strip()
                for item in context.attached_extension_ids
            }
            if extension_id not in attached:
                return deny("extension is not attached to this chat")

        return ExtensionAuthorityDecision(
            allowed=True,
            reason="authorized",
            capability=capability,
            required_permission=required_permission,
            scope=context.scope,
            extension=extension,
        )

    def authorize_preset(self, preset_id, capability, context):
        if self.extension_store is None:
            return ExtensionAuthorityDecision(
                allowed=False,
                reason="extension store is unavailable",
                capability=str(capability or "").strip().lower(),
                required_permission=permission_for_capability(capability),
                scope=context.scope,
                extension=None,
            )

        extension = self.extension_store.find_by_preset_id(preset_id)
        if extension is None:
            return ExtensionAuthorityDecision(
                allowed=False,
                reason=f"extension preset is not installed: {preset_id}",
                capability=str(capability or "").strip().lower(),
                required_permission=permission_for_capability(capability),
                scope=context.scope,
                extension=None,
            )
        return self.authorize_extension(extension, capability, context)

    def resolve_preset(self, preset_id, capability, context):
        decision = self.authorize_preset(
            preset_id,
            capability,
            context,
        )
        return decision.extension if decision.allowed else None
