from app.secret_store import SecretStore


class FakeBackend:
    def __init__(self):
        self.data = {}

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def get_password(self, service, username):
        return self.data.get((service, username))

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


def test_secret_store_round_trip_without_plaintext_file():
    backend = FakeBackend()
    store = SecretStore(backend=backend)

    ref = "extension:abc123:discord_webhook_url"
    store.set_secret(ref, "https://discord.com/api/webhooks/123/token-value")

    assert store.get_secret(ref).endswith("/token-value")
    assert backend.data[("LocalAI-Desktop", ref)].endswith("/token-value")
    assert store.delete_secret(ref) is True
    assert store.get_secret(ref) is None


def test_secret_store_rejects_empty_or_unsafe_reference():
    backend = FakeBackend()
    store = SecretStore(backend=backend)

    for ref in ("", "x y", "abc/def"):
        try:
            store.set_secret(ref, "secret")
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe reference must fail: {ref!r}")
