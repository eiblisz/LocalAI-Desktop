from pathlib import Path

from app.artifact_utils import artifact_url


def test_artifact_url_is_file_uri(tmp_path: Path):
    path = tmp_path / "report.html"
    url = artifact_url(path)

    assert url.startswith("file:")
    assert "report.html" in url
