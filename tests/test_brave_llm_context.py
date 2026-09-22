import os

import pytest

from app import brave_llm_context, web_search_tool


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("request failed")

    def json(self):
        return self._payload


def _official_shape():
    return {
        "grounding": {
            "generic": [
                {
                    "url": "https://example.com/source",
                    "title": "Example Source",
                    "snippets": [
                        "Relevant first passage.",
                        "Relevant second passage.",
                    ],
                }
            ]
        },
        "sources": {
            "https://example.com/source": {
                "site_name": "Example",
                "description": "Example description",
                "age": ["2 days ago", "2026-09-20"],
            }
        },
    }


def test_llm_context_official_response_normalizes_to_existing_result_shape():
    payload = brave_llm_context.normalize_llm_context_response(
        _official_shape(),
        query="example query",
        limit=6,
    )

    assert payload["provider"] == "Brave LLM Context"
    assert payload["pre_extracted_context"] is True
    assert payload["context_mode"] == "llm_context"
    assert payload["results"] == [
        {
            "title": "Example Source",
            "url": "https://example.com/source",
            "snippet": "Relevant first passage.",
            "published": "2026-09-20",
            "page_text": "Relevant first passage.\nRelevant second passage.",
            "source_metadata": {
                "site_name": "Example",
                "description": "Example description",
                "age": ["2 days ago", "2026-09-20"],
            },
        }
    ]


def test_llm_context_request_uses_existing_brave_key_without_exposing_it():
    seen = {}
    secret = "super-secret-brave-key"

    def requester(url, params, headers, timeout):
        seen["url"] = url
        seen["params"] = dict(params)
        seen["headers"] = dict(headers)
        seen["timeout"] = timeout
        return FakeResponse(_official_shape())

    payload = brave_llm_context.search_brave_llm_context(
        "example",
        api_key=secret,
        requester=requester,
    )

    assert seen["url"] == brave_llm_context.BRAVE_LLM_CONTEXT_URL
    assert seen["headers"]["X-Subscription-Token"] == secret
    assert secret not in repr(payload)


def test_search_web_llm_context_skips_local_page_fetch(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret-test-key")
    monkeypatch.setenv("BRAVE_CONTEXT_MODE", "llm_context")
    monkeypatch.setattr(
        web_search_tool,
        "search_brave_llm_context",
        lambda *args, **kwargs: {
            "provider": "Brave LLM Context",
            "context_mode": "llm_context",
            "pre_extracted_context": True,
            "results": [{
                "title": "Nimbus history",
                "url": "https://example.com/nimbus",
                "snippet": "Nimbus was created in 2018.",
                "published": "2026-09-20",
                "page_text": "Nimbus was created in 2018 by Example Author.",
                "source_metadata": {"site_name": "Example"},
            }],
        },
    )
    monkeypatch.setattr(
        web_search_tool,
        "_fetch_top_pages",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("LLM Context must not fetch pages locally")
        ),
    )

    payload = web_search_tool.search_web("Nimbus history", fetch_pages=True)

    assert payload["provider"] == "Brave LLM Context"
    assert payload["context_mode"] == "llm_context"
    assert payload["timing"]["page_fetch_count"] == 0
    assert payload["evidence"][0]["url"] == "https://example.com/nimbus"
    assert payload["evidence"][0]["source_metadata"]["site_name"] == "Example"


def test_llm_context_failure_falls_back_to_legacy_brave(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret-test-key")
    monkeypatch.setenv("BRAVE_CONTEXT_MODE", "llm_context")
    monkeypatch.setattr(
        web_search_tool,
        "search_brave_llm_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("context unavailable")
        ),
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_brave_api",
        lambda *args, **kwargs: {
            "provider": "Brave Search API",
            "results": [{
                "title": "Example legacy result",
                "url": "https://example.com/legacy",
                "snippet": "Legacy evidence for Nimbus.",
                "published": "",
                "page_text": "",
            }],
        },
    )

    payload = web_search_tool.search_web(
        "Nimbus legacy evidence",
        fetch_pages=False,
    )

    assert payload["provider"] == "Brave Search API"
    assert payload["context_mode"] == "legacy"
    assert any(
        note.startswith("Brave LLM Context:")
        for note in payload["provider_chain_errors"]
    )


def test_legacy_mode_never_calls_llm_context(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "secret-test-key")
    monkeypatch.setenv("BRAVE_CONTEXT_MODE", "legacy")
    monkeypatch.setattr(
        web_search_tool,
        "search_brave_llm_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy mode must not call LLM Context")
        ),
    )
    monkeypatch.setattr(
        web_search_tool,
        "_search_brave_api",
        lambda *args, **kwargs: {
            "provider": "Brave Search API",
            "results": [{
                "title": "Example",
                "url": "https://example.com/result",
                "snippet": "Example evidence",
                "published": "",
                "page_text": "",
            }],
        },
    )

    payload = web_search_tool.search_web("Example evidence", fetch_pages=False)
    assert payload["provider"] == "Brave Search API"


def test_llm_context_http_error_never_echoes_api_key():
    secret = "do-not-log-this"

    response = FakeResponse(
        {"error": {"code": "RATE_LIMITED", "detail": "quota exceeded"}},
        status_code=429,
    )

    with pytest.raises(brave_llm_context.BraveLLMContextError) as exc:
        brave_llm_context.search_brave_llm_context(
            "example",
            api_key=secret,
            requester=lambda *args, **kwargs: response,
        )

    assert secret not in str(exc.value)
    assert "HTTP 429" in str(exc.value)
