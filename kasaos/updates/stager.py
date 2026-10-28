"""Safe extraction of a verified artifact into versions/<ver>, never touching other versions."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from kasaos.core.exceptions import UpdateError
from kasaos.updates.install_state import APP_EXE, VERSION_FILE, is_complete_version, version_dir, versions_dir

log = logging.getLogger(__name__)

MAX_ENTRIES = 20000
MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename.replace("\\", "/")
    p = PurePosixPath(name)
    if name.startswith("/") or (p.parts and ":" in p.parts[0]) or ".." in p.parts or not p.parts:
        raise UpdateError(f"Güncelleme arşivinde güvenli olmayan yol: {info.filename}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise UpdateError(f"Güncelleme arşivinde sembolik bağlantı reddedildi: {info.filename}")
    return p


def stage_artifact(zip_path: Path, install_root: Path, version: str) -> Path:
    """Extract into a temp dir, verify, then atomically rename to versions/<version>."""
    target = version_dir(install_root, version)
    if is_complete_version(install_root, version):
        log.info("Version %s already staged", version)
        return target
    vroot = versions_dir(install_root)
    vroot.mkdir(parents=True, exist_ok=True)
    staging = vroot / f".staging-{version}-{uuid.uuid4().hex[:8]}"
    try:
        try:
            zf = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError) as e:
            raise UpdateError(f"Güncelleme arşivi bozuk: {e}") from e
        with zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
                raise UpdateError("Güncelleme arşivi beklenenden büyük.")
            members = [(i, _safe_member(i)) for i in infos]
            names = {str(p) for _, p in members}
            if APP_EXE not in names or VERSION_FILE not in names:
                raise UpdateError("Güncelleme arşivinde gerekli dosyalar eksik.")
            staging.mkdir()
            base = staging.resolve()
            for info, rel in members:
                dest = (staging / Path(*rel.parts)).resolve()
                if base not in dest.parents and dest != base:
                    raise UpdateError(f"Güncelleme arşivinde güvenli olmayan yol: {info.filename}")
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with zf.open(info) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                except (zipfile.BadZipFile, OSError, EOFError) as e:
                    raise UpdateError(f"Güncelleme arşivi açılırken hata: {e}") from e
        found = (staging / VERSION_FILE).read_text(encoding="utf-8").strip()
        if found != version:
            raise UpdateError(f"Arşivdeki sürüm ({found}) beklenen sürümle ({version}) uyuşmuyor.")
        if (staging / APP_EXE).stat().st_size == 0:
            raise UpdateError("Güncelleme uygulama dosyası boş.")
        if target.exists():
            # an earlier incomplete attempt; it is not referenced by install_state
            shutil.rmtree(target)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if not is_complete_version(install_root, version):
        raise UpdateError("Hazırlanan sürüm doğrulanamadı.")
    log.info("Staged version %s at %s", version, target)
    return target


def cleanup_stale_staging(install_root: Path) -> None:
    vroot = versions_dir(install_root)
    if vroot.exists():
        for p in vroot.glob(".staging-*"):
            shutil.rmtree(p, ignore_errors=True)
