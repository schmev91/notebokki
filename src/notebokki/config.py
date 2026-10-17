"""Path resolution for notebokki's registry and session credential.

This is the only module that decides where files live, so the registry loader, the setup
command and the ignore rules cannot disagree. Nothing here lives inside a repository by default.
"""

import os
from pathlib import Path

APP_DIR = "notebokki"
REGISTRY_FILENAME = "registry.json"
SESSION_DIRNAME = "session"
SESSION_FILENAME = "storage_state.json"


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_DIR


def registry_path(override: Path | None = None) -> Path:
    return Path(override) if override else config_dir() / REGISTRY_FILENAME


def session_path(override: Path | None = None) -> Path:
    """The session file sits in its own directory so the library's lock file and rotated
    rewrites are covered by one 0700 directory rather than one filename."""
    if override:
        return Path(override)
    return config_dir() / SESSION_DIRNAME / SESSION_FILENAME
