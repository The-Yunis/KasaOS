"""Persistent state of a versioned installation (stdlib only).

Layout of an install root:

    <root>\\KasaOS.exe              launcher (never replaced by updates)
    <root>\\versions\\<ver>\\         one complete application per version
    <root>\\install_state.json      this file
    <root>\\run\\                    readiness signal files
    <root>\\logs\\launcher.log
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = "install_state.json"
APP_EXE = "KasaOS-app.exe"
VERSION_FILE = "kasaos-version.txt"
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-]?[A-Za-z0-9.]+)?$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_version_name(v: str) -> bool:
    return bool(_VERSION_RE.match(v or ""))


@dataclass
class InstallState:
    current: str | None = None
    previous: str | None = None
    pending: str | None = None
    attempt: dict | None = None          # {"version", "from", "started_at"} while a candidate is trialled
    failed: dict[str, str] = field(default_factory=dict)   # version -> reason
    last_result: dict | None = None      # {"status", "version", "from", "reason", "at", "acknowledged"}

    @classmethod
    def load(cls, root: Path) -> "InstallState":
        p = Path(root) / STATE_FILE
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A damaged state file must not brick startup; keep a copy and rebuild.
            try:
                p.replace(p.with_suffix(".corrupt-" + datetime.now().strftime("%Y%m%d%H%M%S")))
            except OSError:
                pass
            return cls()
        known = {k: data.get(k) for k in cls.__dataclass_fields__ if k in data}
        st = cls(**known)
        if not isinstance(st.failed, dict):
            st.failed = {}
        return st

    def save(self, root: Path) -> None:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        p = root / STATE_FILE
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)


def versions_dir(root: Path) -> Path:
    return Path(root) / "versions"


def version_dir(root: Path, version: str) -> Path:
    if not valid_version_name(version):
        raise ValueError(f"invalid version name: {version!r}")
    return versions_dir(root) / version


def is_complete_version(root: Path, version: str) -> bool:
    try:
        d = version_dir(root, version)
    except ValueError:
        return False
    vf = d / VERSION_FILE
    return (d / APP_EXE).is_file() and vf.is_file() and vf.read_text(encoding="utf-8").strip() == version
