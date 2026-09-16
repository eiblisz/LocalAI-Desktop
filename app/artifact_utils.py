import os
import subprocess
import sys
from pathlib import Path


def artifact_url(path) -> str:
    return Path(path).resolve().as_uri()


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
