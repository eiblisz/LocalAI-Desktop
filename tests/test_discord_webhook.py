import pytest

from app.discord_webhook import (
    send_discord_test_message,
    test_discord_webhook as run_webhook_test,
    validate_discord_webhook_url,
)


VALID = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz"


class Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return dict(self._body)


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


def test_discord_webhook_send_test_message_waits_for_creation_confirmation():
    calls = []

    def sender(url, params, json, timeout):
        calls.append((url, params, json, timeout))
        return Response(
            200,
            {
                "id": "112233445566778899",
                "channel_id": "998877665544332211",
            },
        )

    result = send_discord_test_message(VALID, sender=sender, timeout=5)

    assert result["status"] == "connected"
    assert result["ok"] is True
    assert "112233445566778899" in result["message"]
    assert "998877665544332211" in result["message"]
    assert calls == [(
        VALID,
        {"wait": "true"},
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


def test_discord_webhook_send_does_not_treat_204_as_confirmed_success():
    result = send_discord_test_message(
        VALID,
        sender=lambda *_args, **_kwargs: Response(204),
    )

    assert result["status"] == "error"
    assert result["ok"] is False


def test_discord_webhook_send_requires_message_id_in_wait_response():
    result = send_discord_test_message(
        VALID,
        sender=lambda *_args, **_kwargs: Response(200, {"channel_id": "123"}),
    )

    assert result["status"] == "error"
    assert result["ok"] is False
    assert "did not confirm message creation" in result["message"]

