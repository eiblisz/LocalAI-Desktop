from app.web_evidence import compact_evidence_authority


def test_compact_factual_authority_prefers_relevant_snippet_over_full_page_noise():
    payload = {
        "provider": "Brave Search API",
        "query": "Who wrote Silver Story?",
        "retrieved_at": "2026-09-22T10:00:00",
        "results": [
            {
                "title": "Silver Story",
                "url": "https://example.com/silver",
                "snippet": "Silver Story was written by Correct Author in 1912.",
                "published": "2026-09-20",
                "page_text": (
                    "NOISY PAGE TEXT " * 200
                    + "Unrelated Person 1890 Other Publication"
                ),
            }
        ],
    }

    authority = compact_evidence_authority(payload)

    assert "Correct Author" in authority
    assert "1912" in authority
    assert "https://example.com/silver" in authority
    assert "NOISY PAGE TEXT" not in authority
    assert "Unrelated Person" not in authority
    assert "1890" not in authority


def test_compact_factual_authority_uses_bounded_page_prefix_only_when_snippet_missing():
    payload = {
        "provider": "Brave LLM Context",
        "query": "Example",
        "retrieved_at": "2026-09-22T10:00:00",
        "results": [
            {
                "title": "Example",
                "url": "https://example.com",
                "snippet": "",
                "page_text": "A" * 1200,
            }
        ],
    }

    authority = compact_evidence_authority(
        payload,
        max_text_chars=300,
    )

    assert "A" * 300 in authority
    assert "A" * 301 not in authority


def test_compact_factual_authority_is_bounded_by_source_count():
    payload = {
        "provider": "Brave Search API",
        "query": "Example",
        "retrieved_at": "2026-09-22T10:00:00",
        "results": [
            {
                "title": f"Source {index}",
                "url": f"https://example.com/{index}",
                "snippet": f"Evidence {index}",
                "page_text": "",
            }
            for index in range(8)
        ],
    }

    authority = compact_evidence_authority(payload, max_sources=3)

    assert "Source 0" in authority
    assert "Source 2" in authority
    assert "Source 3" not in authority



def test_compact_factual_authority_includes_host_authoritative_current_fact():
    payload = {
        "provider": "Brave Search API",
        "query": "Ollama latest version release",
        "retrieved_at": "2026-09-22T10:00:00",
        "results": [
            {
                "title": "Releases · ollama/ollama · GitHub",
                "url": "https://github.com/ollama/ollama/releases",
                "snippet": "Official releases",
                "page_text": "Release list v0.34.2 Latest",
            }
        ],
    }

    authority = compact_evidence_authority(
        payload,
        authoritative_fact={
            "kind": "latest_release",
            "value": "v0.34.2",
            "authority": "first_party",
            "title": "Releases · ollama/ollama · GitHub",
            "url": "https://github.com/ollama/ollama/releases",
        },
    )

    assert "AUTHORITATIVE CURRENT FACT" in authority
    assert "Value: v0.34.2" in authority
    assert "Authority: first_party" in authority
    assert "Source URL: https://github.com/ollama/ollama/releases" in authority
