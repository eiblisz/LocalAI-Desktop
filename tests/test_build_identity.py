from app import build_identity


def test_build_identity_rejects_unstamped_or_invalid_sha(monkeypatch):
    monkeypatch.setattr(build_identity, "BUILD_SHA", "not-a-sha")
    monkeypatch.setattr(build_identity, "EXPECTED_MAIN_SHA", "")

    assert build_identity.build_identity() == {
        "build_sha": "source",
        "expected_main_sha": "unknown",
    }
    assert build_identity.short_build_sha() == "source"


def test_build_identity_exposes_stamped_full_and_short_sha(monkeypatch):
    build_sha = "0123456789abcdef0123456789abcdef01234567"
    main_sha = "89abcdef0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(build_identity, "BUILD_SHA", build_sha.upper())
    monkeypatch.setattr(build_identity, "EXPECTED_MAIN_SHA", main_sha)

    assert build_identity.build_identity() == {
        "build_sha": build_sha,
        "expected_main_sha": main_sha,
    }
    assert build_identity.short_build_sha() == build_sha[:12]
