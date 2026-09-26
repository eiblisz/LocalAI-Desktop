from app.user_error_messages import public_error


def test_grounding_exception_has_safe_hungarian_public_wording():
    raw = "Grounded answer still contains unsupported factual literals: Example Name"
    result = public_error(raw)

    assert result.code == "grounding_verification_failed"
    assert "Example Name" not in result.message
    assert "Grounded answer" not in result.message


def test_no_source_exception_has_safe_hungarian_public_wording():
    result = public_error("Web research returned no usable public sources.")

    assert result.code == "no_usable_public_sources"
    assert "nyilvános forrást" in result.message


def test_fluency_audit_exception_has_safe_hungarian_public_wording():
    result = public_error("fluency_audit_failed: invalid structured audit response")

    assert result.code == "fluency_audit_failed"
    assert "strukturált" not in result.message
