"""Update orchestration (no Qt). The UI runs these steps in worker threads.

check()   — discover the newest compatible, correctly signed release.
prepare() — download, verify size + SHA-256, stage into versions/<v>,
            back up the database, mark the version pending.
handoff() — start the launcher (separate process) and let the app exit.

Nothing touches the active installation; the launcher switches versions only
after the candidate signals readiness (see launcher_core).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from kasaos.core.exceptions import UpdateError
from kasaos.updates import manifest as mf
from kasaos.updates.github_client import GitHubReleaseClient, Release
from kasaos.updates.install_state import InstallState
from kasaos.updates.launcher_core import request_update
from kasaos.updates.stager import cleanup_stale_staging, sha256_file, stage_artifact

log = logging.getLogger(__name__)

LAUNCHER_EXE = "KasaOS.exe"


@dataclass
class UpdateCheck:
    status: str                      # "none", "available", "not_configured", "error"
    message: str = ""
    manifest: mf.Manifest | None = None
    release: Release | None = None
    previously_failed: str = ""      # reason, if this version failed before
    rollback_safe: bool = True
    skipped: list[str] = field(default_factory=list)


class UpdateService:
    def __init__(self, *, current_version: str, app_schema: int, platform: str, updates_dir: Path,
                 install_root: Path | None, public_keys: list[str],
                 source: Callable[[], tuple[str, str, bool]],
                 client_factory: Callable[[str, str], GitHubReleaseClient] = GitHubReleaseClient,
                 backup_fn: Callable[[str], object] | None = None):
        self.current_version = current_version
        self.app_schema = app_schema
        self.platform = platform
        self.updates_dir = Path(updates_dir)
        self.install_root = install_root
        self.public_keys = public_keys
        self.source = source
        self.client_factory = client_factory
        self.backup_fn = backup_fn

    @property
    def can_install(self) -> bool:
        return self.install_root is not None

    def check(self) -> UpdateCheck:
        owner, repo, prerelease = self.source()
        if not owner or not repo:
            return UpdateCheck("not_configured", "Güncelleme kaynağı yapılandırılmamış (Ayarlar > Güncelleme).")
        try:
            client = self.client_factory(owner, repo)
            releases = client.releases(include_prerelease=prerelease)
        except UpdateError as e:
            log.warning("Update check failed: %s", e)
            return UpdateCheck("error", str(e))

        current = mf.parse_version(self.current_version)
        candidates = []
        for r in releases:
            try:
                v = mf.parse_version(r.tag.lstrip("vV"))
            except UpdateError:
                continue
            if v > current:
                candidates.append((v, r))
        candidates.sort(key=lambda x: x[0], reverse=True)

        skipped = []
        for v, rel in candidates:
            try:
                m = self._load_manifest(client, rel)
            except UpdateError as e:
                log.warning("Release %s rejected: %s", rel.tag, e)
                skipped.append(f"{rel.tag}: {e}")
                continue
            if mf.parse_version(m.version) != v:
                skipped.append(f"{rel.tag}: etiket ile güncelleme bilgisindeki sürüm uyuşmuyor")
                continue
            problems = mf.check_compatibility(m, self.current_version, self.platform, self.app_schema)
            if problems:
                skipped.append(f"{rel.tag}: {' '.join(problems)}")
                continue
            failed = ""
            if self.install_root is not None:
                failed = InstallState.load(self.install_root).failed.get(m.version, "")
            return UpdateCheck("available", f"KasaOS {m.version} kullanılabilir.", m, rel, failed,
                               mf.rollback_safe(m, self.app_schema), skipped)
        msg = "KasaOS güncel." if not skipped else "Uygun bir güncelleme bulunamadı."
        return UpdateCheck("none", msg, skipped=skipped)

    def _load_manifest(self, client: GitHubReleaseClient, rel: Release) -> mf.Manifest:
        asset = rel.assets.get(mf.MANIFEST_NAME)
        sig = rel.assets.get(mf.SIGNATURE_NAME)
        if asset is None or sig is None:
            raise UpdateError("Sürümde imzalı güncelleme bilgisi yok.")
        data = client.fetch_small(asset, mf.MAX_MANIFEST_BYTES)
        signature = client.fetch_small(sig, 4096)
        mf.verify_signature(data, signature, self.public_keys)
        return mf.parse_manifest(data)

    def prepare(self, check: UpdateCheck, progress: Callable[[str, int, int], None] | None = None,
                cancelled: Callable[[], bool] | None = None) -> str:
        """Download, verify and stage. Returns the staged version. Does not switch versions."""
        if self.install_root is None:
            raise UpdateError("Bu kurulum otomatik güncellemeyi desteklemiyor (geliştirme modu veya "
                              "başlatıcı olmadan çalışıyor).")
        if check.status != "available" or check.manifest is None or check.release is None:
            raise UpdateError("Kurulacak güncelleme yok.")
        m = check.manifest
        art = m.artifact_for(self.platform)
        asset = check.release.assets.get(art.name)
        if asset is None:
            raise UpdateError(f"Sürümde {art.name} dosyası bulunamadı.")

        def report(stage: str, done: int = 0, total: int = 0):
            if progress:
                progress(stage, done, total)

        work = self.updates_dir / m.version
        work.mkdir(parents=True, exist_ok=True)
        final = work / art.name
        part = work / (art.name + ".part")
        owner, repo, _ = self.source()
        client = self.client_factory(owner, repo)

        if not (final.exists() and final.stat().st_size == art.size and sha256_file(final) == art.sha256):
            final.unlink(missing_ok=True)
            report("download", 0, art.size)
            try:
                client.download(asset, part, art.size, lambda d, t: report("download", d, t), cancelled)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            report("verify")
            digest = sha256_file(part)
            if digest != art.sha256:
                part.unlink(missing_ok=True)
                raise UpdateError("İndirilen dosyanın SHA-256 özeti eşleşmiyor; dosya reddedildi.")
            os.replace(part, final)
        log.info("Artifact verified: %s", final)

        report("stage")
        cleanup_stale_staging(self.install_root)
        stage_artifact(final, self.install_root, m.version)

        report("backup")
        if self.backup_fn is not None:
            self.backup_fn(f"pre-update-{m.version}")

        request_update(self.install_root, m.version)
        log.info("Update %s staged and marked pending", m.version)
        report("ready")
        return m.version

    def handoff(self) -> None:
        """Start the launcher, which waits for this process to exit before switching."""
        if self.install_root is None:
            raise UpdateError("Başlatıcı bulunamadı.")
        exe = self.install_root / LAUNCHER_EXE
        if not exe.is_file():
            raise UpdateError(f"Başlatıcı bulunamadı: {exe}")
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(exe), "--wait-pid", str(os.getpid())], cwd=str(self.install_root),
                         creationflags=flags, close_fds=True)
        log.info("Launcher started for update handoff")
