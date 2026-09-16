from pathlib import Path

from app.artifact_utils import artifact_url, path_from_artifact_url


def test_artifact_url_is_file_uri(tmp_path: Path):
    path = tmp_path / "report.html"
    url = artifact_url(path)

    assert url.startswith("file:")
    assert "report.html" in url


def test_artifact_file_uri_roundtrip(tmp_path: Path):
    path = (tmp_path / "folder with space" / "report.xlsx").resolve()
    url = artifact_url(path)
    restored = path_from_artifact_url(url)

    assert restored == path
