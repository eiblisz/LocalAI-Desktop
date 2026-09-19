import re
from urllib.parse import urlparse

import requests


_DISCORD_HOSTS = {"discord.com", "www.discord.com", "discordapp.com", "www.discordapp.com"}


def validate_discord_webhook_url(value):
    url = str(value or "").strip()
    if not url:
        raise ValueError("Discord webhook URL is required")

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _DISCORD_HOSTS:
        raise ValueError("Discord webhook URL must use https://discord.com")

    if not re.fullmatch(r"/api/webhooks/\d+/[^/?#]+/?", parsed.path or ""):
        raise ValueError("Discord webhook URL format is invalid")

    if parsed.query or parsed.fragment:
        raise ValueError("Discord webhook URL must not include query or fragment data")

    return url.rstrip("/")


def test_discord_webhook(webhook_url, requester=requests.get, timeout=10):
    url = validate_discord_webhook_url(webhook_url)
    try:
        response = requester(url, timeout=float(timeout))
    except requests.RequestException as exc:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord connection failed: {exc}",
        }

    code = int(getattr(response, "status_code", 0) or 0)
    if code == 200:
        return {
            "status": "connected",
            "ok": True,
            "message": "Discord webhook is valid (HTTP 200).",
        }
    if code in {401, 403, 404}:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord webhook was rejected (HTTP {code}).",
        }
    return {
        "status": "error",
        "ok": False,
        "message": f"Discord returned HTTP {code or 'unknown'}.",
    }


def send_discord_test_message(webhook_url, sender=requests.post, timeout=10):
    url = validate_discord_webhook_url(webhook_url)
    payload = {
        "content": "LocalAI Desktop extension test: Discord webhook connection is working."
    }

    try:
        response = sender(
            url,
            params={"wait": "true"},
            json=payload,
            timeout=float(timeout),
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord test message failed: {exc}",
        }

    code = int(getattr(response, "status_code", 0) or 0)
    if code != 200:
        return {
            "status": "error",
            "ok": False,
            "message": f"Discord test message was rejected (HTTP {code or 'unknown'}).",
        }

    try:
        body = response.json()
    except Exception:
        body = {}

    message_id = str(body.get("id", "") or "").strip()
    channel_id = str(body.get("channel_id", "") or "").strip()
    if not message_id:
        return {
            "status": "error",
            "ok": False,
            "message": "Discord returned HTTP 200 but did not confirm message creation.",
        }

    suffix = f" in channel {channel_id}" if channel_id else ""
    return {
        "status": "connected",
        "ok": True,
        "message": f"Discord test message confirmed{suffix} (message {message_id}).",
    }
