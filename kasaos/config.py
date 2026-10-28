"""Filesystem locations and static configuration.

User data is deliberately kept away from the installation directory so that an
update (which replaces program files) can never touch the database.

    %LOCALAPPDATA%\\KasaOS\\data      database
    %LOCALAPPDATA%\\KasaOS\\logs      rotating logs
    %LOCALAPPDATA%\\KasaOS\\backups   verified database backups
    %LOCALAPPDATA%\\KasaOS\\updates   downloads / temporary update files

The install root (launcher + versions/) lives in %LOCALAPPDATA%\\Programs\\KasaOS
and is passed to the app by the launcher via KASAOS_INSTALL_ROOT.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Trusted release source. Can be overridden in Settings; changing it does not
# change the trusted signing key (see kasaos/updates/trust.py).
# https://github.com/The-Yunis/KasaOS
DEFAULT_GITHUB_OWNER = "The-Yunis"
DEFAULT_GITHUB_REPO = "KasaOS"

# Environment variables used between launcher and application.
ENV_HOME = "KASAOS_HOME"
ENV_INSTALL_ROOT = "KASAOS_INSTALL_ROOT"
ENV_READY_FILE = "KASAOS_READY_FILE"
ENV_UPDATE_NOTICE = "KASAOS_UPDATE_NOTICE"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def database(self) -> Path:
        return self.data_dir / "kasaos.db"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def updates_dir(self) -> Path:
        return self.root / "updates"

    @property
    def quarantine_dir(self) -> Path:
        return self.root / "quarantine"

    def ensure(self) -> None:
        for d in (self.data_dir, self.logs_dir, self.backups_dir, self.updates_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_paths() -> AppPaths:
    override = os.environ.get(ENV_HOME)
    if override:
        return AppPaths(Path(override))
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return AppPaths(Path(base) / "KasaOS")


def install_root() -> Path | None:
    """Install root when running under the launcher in a packaged build."""
    value = os.environ.get(ENV_INSTALL_ROOT)
    if value and getattr(sys, "frozen", False):
        return Path(value)
    return None


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if getattr(sys, "frozen", False):
        return base / "kasaos" / "resources" / Path(*parts)
    return base / "resources" / Path(*parts)
