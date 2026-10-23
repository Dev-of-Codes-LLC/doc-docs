"""Where DOC Docs keeps things outside the repos it works on."""

import os
import sys
from pathlib import Path


def user_dir() -> Path:
    """Per-user data: voices and the voice cache. Never inside a repo."""
    override = os.environ.get("DOCDOCS_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "docdocs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "docdocs"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "docdocs"


def package_dir() -> Path:
    return Path(__file__).resolve().parent
