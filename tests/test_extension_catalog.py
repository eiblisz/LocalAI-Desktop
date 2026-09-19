from app.extension_catalog import (
    PRESET_CATEGORIES,
    all_presets,
    find_preset,
    preset_to_registry_entry,
    search_presets,
)


def test_catalog_contains_requested_categories_and_key_presets():
    assert PRESET_CATEGORIES == (
        "Productivity",
        "Creativity",
        "Developer Tools",
        "Business & Operations",
        "Communication",
    )

    names = {item["name"] for item in all_presets()}
    for expected in {
        "Google Calendar",
        "Notion",
        "Dropbox",
        "Canva",
        "Figma",
        "Adobe",
        "GitHub",
        "Supabase",
        "HubSpot",
        "Discord Webhook",
        "Prometheusz Discord Bot",
        "Crypto Market Data",
        "TradingView Workspace",
    }:
        assert expected in names


def test_catalog_search_matches_name_description_and_capability():
    assert [item["name"] for item in search_presets("github")] == ["GitHub"]

    creativity = search_presets("", "Creativity")
    assert creativity
    assert all(item["category"] == "Creativity" for item in creativity)

    repo_matches = search_presets("repo_read")
    assert any(item["name"] == "GitHub" for item in repo_matches)


def test_find_preset_returns_copy_and_unknown_id_raises():
    github = find_preset("github")
    github["name"] = "Changed"

    assert find_preset("github")["name"] == "GitHub"

    try:
        find_preset("missing")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown preset id must raise KeyError")


def test_preset_install_payload_is_disabled_and_secret_free():
    preset = find_preset("github")
    payload = preset_to_registry_entry(preset)

    assert payload["name"] == "GitHub"
    assert payload["type"] == "mcp_connector"
    assert payload["enabled"] is False
    assert payload["endpoint"] == ""
    assert payload["auth_type"] == "oauth"
    assert payload["config"]["preset_id"] == "github"
    assert payload["config"]["provider_url"].startswith("https://")

    serialized = repr(payload).lower()
    assert "access_token" not in serialized
    assert "client_secret" not in serialized
    assert "password" not in serialized


def test_discord_webhook_preset_is_secret_url_metadata_only():
    preset = find_preset("discord-webhook")
    payload = preset_to_registry_entry(preset)

    assert preset["category"] == "Communication"
    assert preset["auth_type"] == "secret_url"
    assert preset["capabilities"] == ("send_message", "send_embed")
    assert payload["endpoint"] == ""
    assert payload["enabled"] is False
    assert payload["config"]["preset_id"] == "discord-webhook"
    assert "webhook" not in payload.get("credential_ref", "").lower()


def test_prometheusz_discord_bot_preset_has_remote_chat_allowlist_defaults():
    preset = find_preset("discord-bot")
    payload = preset_to_registry_entry(preset)

    assert preset["category"] == "Communication"
    assert preset["auth_type"] == "bot_token"
    assert preset["capabilities"] == (
        "read_messages",
        "send_message",
        "remote_chat",
        "web_research",
        "artifact_pdf",
        "artifact_docx",
        "artifact_xlsx",
        "artifact_html",
        "artifact_summary",
        "file_upload",
    )
    assert payload["enabled"] is False
    assert payload["config"]["guild_id"] == ""
    assert payload["config"]["channel_id"] == ""
    assert payload["config"]["allowed_user_id"] == ""
    assert payload["config"]["model"] == ""


def test_crypto_market_data_preset_is_public_no_auth_and_preconfigured():
    preset = find_preset("crypto-market-data")
    payload = preset_to_registry_entry(preset)

    assert preset["category"] == "Business & Operations"
    assert preset["auth_type"] == "none"
    assert preset["capabilities"] == (
        "crypto_quote",
        "crypto_ticker",
        "crypto_24h",
    )
    assert payload["enabled"] is False
    assert payload["endpoint"] == "https://api.exchange.coinbase.com/time"
    assert payload["config"]["api_base_url"] == "https://api.exchange.coinbase.com"
    assert payload["config"]["default_quote"] == "USD"



def test_tradingview_workspace_preset_is_browser_only_and_multi_asset():
    preset = find_preset("tradingview-workspace")
    payload = preset_to_registry_entry(preset)

    assert preset["category"] == "Business & Operations"
    assert preset["type"] == "custom_tool"
    assert preset["auth_type"] == "none"
    assert {
        "market_chart",
        "stocks",
        "crypto",
        "forex",
        "indices",
        "market_visualization",
    }.issubset(set(preset["capabilities"]))
    assert payload["enabled"] is False
    assert payload["endpoint"] == ""
    assert payload["config"]["workspace_url"] == "https://www.tradingview.com/markets/"
    assert payload["config"]["provider"] == "tradingview_browser_workspace"
