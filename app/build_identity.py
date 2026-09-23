import re


_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

try:
    from ._build_metadata import BUILD_SHA, EXPECTED_MAIN_SHA
except ImportError:
    BUILD_SHA = "source"
    EXPECTED_MAIN_SHA = "unknown"


def _normalized_sha(value, fallback):
    candidate = str(value or "").strip().lower()
    return candidate if _SHA_PATTERN.fullmatch(candidate) else fallback


def build_identity():
    return {
        "build_sha": _normalized_sha(BUILD_SHA, "source"),
        "expected_main_sha": _normalized_sha(EXPECTED_MAIN_SHA, "unknown"),
    }


def short_build_sha():
    value = build_identity()["build_sha"]
    return value[:12] if value != "source" else value
