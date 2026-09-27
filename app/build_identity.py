import re
import subprocess
from pathlib import Path


_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

try:
    from ._build_metadata import BUILD_SHA, EXPECTED_MAIN_SHA
except ImportError:
    BUILD_SHA = "source"
    EXPECTED_MAIN_SHA = "unknown"


def _normalized_sha(value, fallback):
    candidate = str(value or "").strip().lower()
    return candidate if _SHA_PATTERN.fullmatch(candidate) else fallback


def _source_git_sha(ref="HEAD"):
    """Resolve a source checkout SHA without affecting packaged builds.

    Source-mode diagnostics used to report only a generic source marker, which
    made it impossible to distinguish a freshly pulled checkout from a stale
    running process or a different working tree. Stamped build metadata remains
    authoritative; this fallback is used only when no valid stamp exists.
    """
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", str(ref)],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    if completed.returncode != 0:
        return ""
    return _normalized_sha(completed.stdout, "")


def build_identity():
    stamped_build = _normalized_sha(BUILD_SHA, "")
    stamped_main = _normalized_sha(EXPECTED_MAIN_SHA, "")
    build_sha = stamped_build or _source_git_sha("HEAD") or "source"
    expected_main_sha = (
        stamped_main
        or _source_git_sha("origin/main")
        or "unknown"
    )
    return {
        "build_sha": build_sha,
        "expected_main_sha": expected_main_sha,
    }


def short_build_sha():
    value = build_identity()["build_sha"]
    return value[:12] if value != "source" else value
