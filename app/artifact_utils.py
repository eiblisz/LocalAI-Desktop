import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def artifact_url(path) -> str:
    return Path(path).resolve().as_uri()


def path_from_artifact_url(url: str) -> Path:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "file":
        raise ValueError("Only local file:// artifact URLs are supported.")

    raw_path = unquote(parsed.path)

    if sys.platform.startswith("win"):
        if parsed.netloc:
            return Path(f"//{parsed.netloc}{raw_path}")
        if re.match(r"^/[A-Za-z]:/", raw_path):
            raw_path = raw_path[1:]

    return Path(raw_path)


def open_file(path) -> None:
    target = Path(path).resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def open_folder(path) -> None:
    target = Path(path).resolve()
    folder = target if target.is_dir() else target.parent
    if sys.platform.startswith("win"):
        os.startfile(str(folder))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
