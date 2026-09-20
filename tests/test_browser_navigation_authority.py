from pathlib import Path

from app.browser_navigation_authority import (
    ACTION_BLOCK,
    ACTION_EXTERNAL,
    ACTION_INTERNAL_SAME,
    ACTION_INTERNAL_TAB,
    BrowserNavigationAuthority,
)


def test_http_navigation_stays_inside_localai_by_default():
    authority = BrowserNavigationAuthority()

    initial = authority.decide(
        "https://example.com",
        source="initial_load",
    )
    page = authority.decide(
        "https://example.com/next",
        source="page_link",
    )
    popup = authority.decide(
        "https://example.com/popup",
        source="new_window",
    )
    chat = authority.decide(
        "https://example.com/from-chat",
        source="resource_open",
    )

    assert initial.action == ACTION_INTERNAL_SAME
    assert page.action == ACTION_INTERNAL_SAME
    assert popup.action == ACTION_INTERNAL_TAB
    assert chat.action == ACTION_INTERNAL_TAB


def test_external_application_launch_requires_explicit_external_button():
    authority = BrowserNavigationAuthority()

    automatic = authority.decide(
        "https://example.com",
        source="page_link",
    )
    explicit = authority.decide(
        "https://example.com",
        source="external_button",
    )

    assert automatic.action == ACTION_INTERNAL_SAME
    assert explicit.action == ACTION_EXTERNAL
    assert "explicit user-requested" in explicit.reason


def test_address_bar_normalizes_bare_hostname_to_internal_https():
    authority = BrowserNavigationAuthority()

    decision = authority.decide(
        "example.com/path",
        source="address_bar",
    )

    assert decision.action == ACTION_INTERNAL_SAME
    assert decision.target == "https://example.com/path"


def test_unsafe_or_unhandled_schemes_fail_closed():
    authority = BrowserNavigationAuthority()

    for target in (
        "javascript:alert(1)",
        "data:text/html,hello",
        "mailto:test@example.com",
        "ftp://example.com/file",
        "customtool://run",
    ):
        decision = authority.decide(
            target,
            source="page_link",
        )
        assert decision.action == ACTION_BLOCK
        assert decision.allowed is False


def test_local_file_navigation_requires_existing_target(tmp_path):
    authority = BrowserNavigationAuthority()
    existing = tmp_path / "report.html"
    existing.write_text("<html>ok</html>", encoding="utf-8")

    allowed = authority.decide(
        existing.as_uri(),
        source="resource_open",
    )
    missing = authority.decide(
        (tmp_path / "missing.html").as_uri(),
        source="resource_open",
    )

    assert allowed.action == ACTION_INTERNAL_TAB
    assert missing.action == ACTION_BLOCK


def test_local_file_external_open_is_explicit_only(tmp_path):
    authority = BrowserNavigationAuthority()
    existing = tmp_path / "report.html"
    existing.write_text("<html>ok</html>", encoding="utf-8")

    internal = authority.decide(
        existing.as_uri(),
        source="page_link",
    )
    external = authority.decide(
        existing.as_uri(),
        source="external_button",
    )

    assert internal.action == ACTION_INTERNAL_SAME
    assert external.action == ACTION_EXTERNAL
