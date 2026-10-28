"""KasaOS launcher — the small, stable KasaOS.exe users start.

Starts the active version from versions/<ver>, and performs the guarded
switch to a staged update (see kasaos/updates/launcher_core.py).
Stdlib only. Coded by Yunus Açıkgöz
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from kasaos.updates.launcher_core import Launcher, wait_for_pid_exit


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(os.environ.get("KASAOS_INSTALL_ROOT", Path(__file__).resolve().parent))


def _message(text: str) -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "KasaOS", 0x10)
    else:
        print(text, file=sys.stderr)


class _SingleLauncher:
    """Prevents two launchers from trialling an update at the same time."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.fh.close()
                return False
        return True

    def __exit__(self, *exc):
        if self.fh and not self.fh.closed:
            self.fh.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="KasaOS")
    parser.add_argument("--wait-pid", type=int, default=0)
    args, _ = parser.parse_known_args(argv)

    root = _root()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / "logs" / "launcher.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    log = logging.getLogger("kasaos.launcher")

    if args.wait_pid:
        log.info("Waiting for process %s to exit", args.wait_pid)
        if not wait_for_pid_exit(args.wait_pid, 60):
            log.error("Process %s did not exit; update postponed", args.wait_pid)
            _message("KasaOS kapanmadığı için güncelleme ertelendi. Uygulamayı yeniden başlatın.")
            return 2

    with _SingleLauncher(root / "run" / "launcher.lock") as acquired:
        if not acquired:
            log.info("Another launcher is active; exiting")
            return 0
        try:
            outcome = Launcher(root).run()
        except Exception:
            log.exception("Launcher failed")
            _message("KasaOS başlatılamadı. Ayrıntılar: " + str(root / "logs" / "launcher.log"))
            return 1
        log.info("Launcher outcome: %s %s %s", outcome.status, outcome.version, outcome.reason)
        if outcome.status in ("no_version", "failed"):
            _message("KasaOS başlatılamadı: " + (outcome.reason or "bilinmeyen hata") +
                     "\n\nVerileriniz korunmaktadır. Lütfen KasaOS'u yeniden kurun.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
