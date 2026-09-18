import pytest

from app.discord_webhook import (
    send_discord_test_message,
    test_discord_webhook as run_webhook_test,
    validate_discord_webhook_url,
)


VALID = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz"


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


def test_validate_discord_webhook_url_accepts_only_https_discord_webhooks():
    assert validate_discord_webhook_url(VALID) == VALID

    for bad in (
        "http://discord.com/api/webhooks/123/token",
        "https://example.com/api/webhooks/123/token",
        "https://discord.com/channels/123/456",
        "https://discord.com/api/webhooks/123/token?wait=true",
    ):
        with pytest.raises(ValueError):
            validate_discord_webhook_url(bad)


def test_discord_webhook_connection_test_uses_secret_url_without_persisting_it():
    calls = []

    def requester(url, timeout):
        calls.append((url, timeout))
        return Response(200)

    result = run_webhook_test(VALID, requester=requester, timeout=7)

    assert result["status"] == "connected"
    assert result["ok"] is True
    assert calls == [(VALID, 7.0)]


def test_discord_webhook_send_test_message_posts_bounded_payload():
    calls = []

    def sender(url, json, timeout):
        calls.append((url, json, timeout))
        return Response(204)

    result = send_discord_test_message(VALID, sender=sender, timeout=5)

    assert result["status"] == "connected"
    assert result["ok"] is True
    assert calls == [(
        VALID,
        {"content": "LocalAI Desktop extension test: Discord webhook connection is working."},
        5.0,
    )]


def test_discord_webhook_rejection_fails_closed():
    result = run_webhook_test(
        VALID,
        requester=lambda *_args, **_kwargs: Response(404),
    )

    assert result["status"] == "error"
    assert result["ok"] is False
