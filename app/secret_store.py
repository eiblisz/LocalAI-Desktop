import re

import keyring
from keyring.errors import KeyringError


_SERVICE_NAME = "LocalAI-Desktop"


def _clean_ref(value):
    ref = str(value or "").strip()
    if not ref:
        raise ValueError("credential reference is required")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{3,200}", ref):
        raise ValueError("credential reference contains unsupported characters")
    return ref


class SecretStore:
    """Thin wrapper over the OS credential backend provided by keyring."""

    def __init__(self, backend=None, service_name=_SERVICE_NAME):
        self.backend = backend or keyring
        self.service_name = str(service_name or _SERVICE_NAME)

    def set_secret(self, credential_ref, secret):
        credential_ref = _clean_ref(credential_ref)
        secret = str(secret or "")
        if not secret:
            raise ValueError("secret value is required")
        try:
            self.backend.set_password(self.service_name, credential_ref, secret)
        except KeyringError as exc:
            raise RuntimeError(f"secure credential storage failed: {exc}") from exc

    def get_secret(self, credential_ref):
        credential_ref = _clean_ref(credential_ref)
        try:
            return self.backend.get_password(self.service_name, credential_ref)
        except KeyringError as exc:
            raise RuntimeError(f"secure credential read failed: {exc}") from exc

    def delete_secret(self, credential_ref):
        credential_ref = _clean_ref(credential_ref)
        try:
            current = self.backend.get_password(self.service_name, credential_ref)
            if current is None:
                return False
            self.backend.delete_password(self.service_name, credential_ref)
            return True
        except KeyringError as exc:
            raise RuntimeError(f"secure credential delete failed: {exc}") from exc
