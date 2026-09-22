from app.web_evidence import compact_evidence_authority, compact_evidence_bundle


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



def test_compact_evidence_bundle_ranks_current_request_relation_evidence_first():
    payloads = [
        {
            "provider": "Brave Search API",
            "query": "broad background",
            "retrieved_at": "2026-09-22T10:00:00",
            "results": [
                {
                    "title": f"Unrelated Market Context {index}",
                    "url": f"https://example.com/unrelated/{index}",
                    "snippet": "General market discussion and unrelated background.",
                }
                for index in range(6)
            ],
        },
        {
            "provider": "Brave Search API",
            "query": "Silver Story author",
            "retrieved_at": "2026-09-22T10:00:01",
            "results": [
                {
                    "title": "Correct Author: Silver Story",
                    "url": "https://example.com/silver-story",
                    "snippet": (
                        "Silver Story is presented as a work by Correct Author "
                        "and was first published in 1912."
                    ),
                }
            ],
        },
    ]

    authority = compact_evidence_bundle(
        payloads,
        user_prompt="Mikor írta Wrong Author a Silver Story című művet?",
        max_sources=3,
        max_total_chars=1800,
    )

    assert "Correct Author: Silver Story" in authority
    assert "1912" in authority
    assert authority.index("Correct Author: Silver Story") < authority.index(
        "Unrelated Market Context"
    )
    assert len(authority) <= 1800


def test_compact_evidence_bundle_has_one_global_budget_across_many_queries():
    payloads = []
    for query_index in range(4):
        payloads.append({
            "provider": "Brave Search API",
            "query": f"Example query {query_index}",
            "retrieved_at": "2026-09-22T10:00:00",
            "results": [
                {
                    "title": f"Example Subject source {query_index}-{result_index}",
                    "url": (
                        f"https://example.com/{query_index}/{result_index}"
                    ),
                    "snippet": "Example Subject " + ("evidence " * 200),
                }
                for result_index in range(6)
            ],
        })

    authority = compact_evidence_bundle(
        payloads,
        user_prompt="Who wrote Example Subject?",
        max_sources=8,
        max_total_chars=2400,
        max_text_chars=420,
    )

    assert authority
    assert len(authority) <= 2400
    assert authority.count("Title:") <= 8
