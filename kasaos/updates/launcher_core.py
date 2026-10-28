"""Launcher / updater logic (stdlib only).

The launcher is the only process that switches the active version. It never
overwrites files of a running program: every version lives in its own folder
and "switching" just means updating install_state.json after the candidate
proved it can start.

Candidate trial:
  1. pending -> recorded as `attempt` and saved BEFORE launching, so if the
     launcher itself dies, the next start treats the attempt as failed
     (no restart loop).
  2. Launch candidate with KASAOS_READY_FILE. The app writes this file once
     its database is open and the main window is shown.
  3. Ready within timeout -> current = candidate, previous = old current.
     Otherwise kill candidate, mark version failed, relaunch old current.
  A failed version is never retried automatically.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from kasaos.updates.install_state import (APP_EXE, InstallState, is_complete_version, now_iso,
                                          version_dir, versions_dir)

log = logging.getLogger("kasaos.launcher")

ENV_READY_FILE = "KASAOS_READY_FILE"
ENV_INSTALL_ROOT = "KASAOS_INSTALL_ROOT"
ENV_UPDATE_NOTICE = "KASAOS_UPDATE_NOTICE"

DEFAULT_READY_TIMEOUT = 90.0

CommandFor = Callable[[Path], list[str]]


def default_command(version_path: Path) -> list[str]:
    return [str(version_path / APP_EXE)]


@dataclass
class LaunchOutcome:
    status: str            # "started", "updated", "rolled_back", "no_version", "failed"
    version: str | None
    process: subprocess.Popen | None = None
    reason: str = ""


def _version_key(v: str):
    parts = []
    for p in v.replace("-", ".").split("."):
        parts.append((0, int(p)) if p.isdigit() else (-1, p))
    return parts


def wait_for_pid_exit(pid: int, timeout: float) -> bool:
    """Wait until process `pid` has exited. Returns False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            WAIT_TIMEOUT = 0x102
            return kernel32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class Launcher:
    def __init__(self, root: Path, command_for: CommandFor = default_command,
                 ready_timeout: float = DEFAULT_READY_TIMEOUT, popen_kwargs: dict | None = None):
        self.root = Path(root)
        self.command_for = command_for
        self.ready_timeout = ready_timeout
        self.popen_kwargs = popen_kwargs or {}

    # -- helpers -----------------------------------------------------------------
    def _spawn(self, version: str, ready_file: Path | None, notice: str | None) -> subprocess.Popen:
        env = dict(os.environ)
        env[ENV_INSTALL_ROOT] = str(self.root)
        env.pop(ENV_READY_FILE, None)
        env.pop(ENV_UPDATE_NOTICE, None)
        if ready_file is not None:
            env[ENV_READY_FILE] = str(ready_file)
        if notice:
            env[ENV_UPDATE_NOTICE] = notice
        vdir = version_dir(self.root, version)
        cmd = self.command_for(vdir)
        log.info("Launching %s: %s", version, cmd)
        return subprocess.Popen(cmd, cwd=str(vdir), env=env, **self.popen_kwargs)

    def _wait_ready(self, proc: subprocess.Popen, ready_file: Path, version: str) -> tuple[bool, str]:
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if ready_file.exists():
                try:
                    data = json.loads(ready_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    time.sleep(0.1)  # file may be mid-write
                    continue
                if data.get("version") == version:
                    return True, ""
                return False, f"hazır sinyali yanlış sürüm bildirdi: {data.get('version')!r}"
            code = proc.poll()
            if code is not None:
                return False, f"uygulama hazır olmadan kapandı (çıkış kodu {code})"
            time.sleep(0.2)
        return False, f"uygulama {int(self.ready_timeout)} sn içinde hazır sinyali vermedi"

    @staticmethod
    def _stop(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def _ready_path(self) -> Path:
        run = self.root / "run"
        run.mkdir(parents=True, exist_ok=True)
        return run / f"ready-{uuid.uuid4().hex}.json"

    def _discover_current(self, st: InstallState) -> str | None:
        if st.current and is_complete_version(self.root, st.current):
            return st.current
        if st.previous and is_complete_version(self.root, st.previous):
            log.warning("Current version %s unusable; falling back to %s", st.current, st.previous)
            return st.previous
        vdir = versions_dir(self.root)
        if not vdir.exists():
            return None
        candidates = sorted((p.name for p in vdir.iterdir()
                             if p.is_dir() and p.name not in st.failed and is_complete_version(self.root, p.name)),
                            key=_version_key, reverse=True)
        return candidates[0] if candidates else None

    def prune(self, st: InstallState) -> None:
        keep = {v for v in (st.current, st.previous) if v}
        vdir = versions_dir(self.root)
        if not vdir.exists():
            return
        # Runs only right after a successful switch, when no other version is in use.
        for p in vdir.iterdir():
            if p.is_dir() and p.name not in keep:
                shutil.rmtree(p, ignore_errors=True)
                log.info("Pruned %s", p)

    # -- main entry ----------------------------------------------------------------
    def run(self) -> LaunchOutcome:
        st = InstallState.load(self.root)

        if st.attempt:
            # A previous launcher died while trialling this version. Treat as failed.
            v = st.attempt.get("version")
            reason = "önceki güncelleme denemesi yarıda kaldı"
            log.error("Interrupted attempt for %s detected; marking failed", v)
            if v:
                st.failed[v] = reason
            st.last_result = {"status": "rolled_back", "version": v, "from": st.attempt.get("from"),
                              "reason": reason, "at": now_iso(), "acknowledged": False}
            st.attempt = None
            st.save(self.root)

        current = self._discover_current(st)
        if current != st.current:
            st.current = current
            st.save(self.root)

        pending = st.pending
        if pending:
            st.pending = None
            if pending in st.failed:
                log.warning("Pending %s previously failed; not retrying automatically", pending)
                st.save(self.root)
            elif pending == current:
                st.save(self.root)
            elif not is_complete_version(self.root, pending):
                log.error("Pending %s is incomplete; ignoring", pending)
                st.failed[pending] = "kurulum dosyaları eksik"
                st.save(self.root)
            else:
                return self._trial(st, pending, current)

        if current is None:
            log.error("No usable KasaOS version found under %s", self.root)
            return LaunchOutcome("no_version", None, reason="kullanılabilir sürüm bulunamadı")
        notice = None
        if st.last_result and not st.last_result.get("acknowledged"):
            notice = json.dumps(st.last_result, ensure_ascii=False)
        return LaunchOutcome("started", current, self._spawn(current, None, notice))

    def _trial(self, st: InstallState, candidate: str, current: str | None) -> LaunchOutcome:
        st.attempt = {"version": candidate, "from": current, "started_at": now_iso()}
        st.save(self.root)
        ready = self._ready_path()
        try:
            proc = self._spawn(candidate, ready, None)
        except OSError as e:
            ok, reason, proc = False, f"başlatılamadı: {e}", None
        else:
            ok, reason = self._wait_ready(proc, ready, candidate)
        ready.unlink(missing_ok=True)

        if ok:
            log.info("Candidate %s passed readiness check", candidate)
            st.previous = current if current != candidate else st.previous
            st.current = candidate
            st.attempt = None
            st.last_result = {"status": "success", "version": candidate, "from": current,
                              "reason": "", "at": now_iso(), "acknowledged": False}
            st.save(self.root)
            self.prune(st)
            return LaunchOutcome("updated", candidate, proc)

        log.error("Candidate %s failed: %s — rolling back to %s", candidate, reason, current)
        if proc is not None:
            self._stop(proc)
        st.failed[candidate] = reason
        st.attempt = None
        st.last_result = {"status": "rolled_back", "version": candidate, "from": current,
                          "reason": reason, "at": now_iso(), "acknowledged": False}
        st.save(self.root)
        if current is None:
            return LaunchOutcome("failed", None, reason=reason)
        notice = json.dumps(st.last_result, ensure_ascii=False)
        return LaunchOutcome("rolled_back", current, self._spawn(current, None, notice), reason)


def acknowledge_last_result(root: Path) -> None:
    st = InstallState.load(root)
    if st.last_result and not st.last_result.get("acknowledged"):
        st.last_result["acknowledged"] = True
        st.save(root)


def request_update(root: Path, version: str) -> None:
    """Called by the app after a version was fully staged under versions/<version>."""
    if not is_complete_version(root, version):
        raise ValueError(f"version {version} is not completely staged")
    st = InstallState.load(root)
    st.pending = version
    st.failed.pop(version, None)  # explicit retry by user clears the block
    st.save(root)


def write_ready_signal(path: Path, version: str) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps({"version": version, "pid": os.getpid(), "at": now_iso()}), encoding="utf-8")
    os.replace(tmp, path)
