"""Verified database backups and safe restore.

Backups use SQLite's online backup API, which is safe while the source runs in
WAL mode (copying the .db file alone would miss un-checkpointed WAL pages).

Restore never overwrites the only valid copy: the current database is first
backed up ("pre-restore"), the chosen backup is verified, copied to a temp file
next to the live DB, verified again, then atomically swapped in with os.replace.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kasaos.core.exceptions import BackupError
from kasaos.infrastructure.database.connection import Database, integrity_ok, open_connection
from kasaos.infrastructure.database.migrations import APP_MARKER, read_meta

log = logging.getLogger(__name__)

BACKUP_SUFFIX = ".kasaosbak"


@dataclass
class BackupInfo:
    path: Path
    created: datetime
    size: int
    schema_version: int
    reason: str


def verify_backup(path: Path) -> int:
    """Raise BackupError unless path is an intact KasaOS database; return its schema version."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise BackupError("Yedek dosyası bulunamadı veya boş.")
    try:
        conn = open_connection(path, readonly=True)
    except sqlite3.DatabaseError as e:
        raise BackupError(f"Yedek dosyası açılamadı: {e}") from e
    try:
        ok, detail = integrity_ok(conn, quick=False)
        if not ok:
            raise BackupError(f"Yedek dosyası bozuk: {detail}")
        try:
            meta = read_meta(conn)
        except sqlite3.DatabaseError as e:
            raise BackupError(f"Yedek dosyası okunamadı: {e}") from e
        if meta.get("app") != APP_MARKER or "schema_version" not in meta:
            raise BackupError("Bu dosya geçerli bir KasaOS yedeği değil.")
        return int(meta["schema_version"])
    except sqlite3.DatabaseError as e:
        raise BackupError(f"Yedek dosyası bozuk: {e}") from e
    finally:
        conn.close()


class BackupService:
    def __init__(self, db: Database, backups_dir: Path, quarantine_dir: Path | None = None):
        self.db = db
        self.backups_dir = Path(backups_dir)
        self.quarantine_dir = Path(quarantine_dir) if quarantine_dir else self.backups_dir.parent / "quarantine"

    def create(self, reason: str = "manual", dest: Path | None = None) -> Path:
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = Path(dest) if dest else self.backups_dir / f"kasaos-{stamp}-{_safe(reason)}{BACKUP_SUFFIX}"
        tmp = target.with_name(target.name + ".partial")
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                with self.db.read() as src:
                    src.backup(dst)
            finally:
                dst.close()
            verify_backup(tmp)
            os.replace(tmp, target)
        except (sqlite3.DatabaseError, OSError, BackupError) as e:
            tmp.unlink(missing_ok=True)
            log.exception("Backup failed")
            raise BackupError(f"Yedek oluşturulamadı: {e}") from e
        log.info("Backup created: %s (%s)", target, reason)
        return target

    def list(self) -> list[BackupInfo]:
        if not self.backups_dir.exists():
            return []
        out = []
        for p in sorted(self.backups_dir.glob(f"*{BACKUP_SUFFIX}"), reverse=True):
            parts = p.stem.split("-", 4)
            reason = parts[4] if len(parts) > 4 else ""
            try:
                conn = open_connection(p, readonly=True)
                try:
                    schema = int(read_meta(conn).get("schema_version", "0"))
                finally:
                    conn.close()
            except (sqlite3.DatabaseError, ValueError):
                schema = -1
            st = p.stat()
            out.append(BackupInfo(p, datetime.fromtimestamp(st.st_mtime), st.st_size, schema, reason))
        return out

    def prune(self, keep: int = 30, reason_prefix: str = "auto") -> int:
        """Remove old automatic backups only; manual / pre-* backups are kept."""
        autos = [b for b in self.list() if b.reason.startswith(reason_prefix)]
        removed = 0
        for b in autos[keep:]:
            b.path.unlink(missing_ok=True)
            removed += 1
        return removed

    def restore(self, backup_path: Path, app_schema: int) -> Path:
        """Replace the live DB with backup_path. Returns the pre-restore safety backup path.

        The caller must reopen the database afterwards (Database.open + migrate).
        """
        schema = verify_backup(backup_path)
        if schema > app_schema:
            raise BackupError("Bu yedek daha yeni bir KasaOS sürümüne ait; bu sürümle geri yüklenemez.")
        live = self.db.path
        if self.db.is_open:
            safety = self.create("pre-restore")
        else:
            # Startup recovery: the live DB could not be opened, keep a raw copy instead.
            safety = quarantine_copy(live, self.quarantine_dir)
        staged = live.with_name(live.name + ".restore-tmp")
        shutil.copy2(backup_path, staged)
        try:
            verify_backup(staged)
        except BackupError:
            staged.unlink(missing_ok=True)
            raise
        self.db.close()
        try:
            for ext in ("-wal", "-shm"):
                Path(str(live) + ext).unlink(missing_ok=True)
            os.replace(staged, live)
        except OSError as e:
            staged.unlink(missing_ok=True)
            raise BackupError(f"Geri yükleme tamamlanamadı, mevcut veri korunuyor: {e}. "
                              f"Güvenlik yedeği: {safety}") from e
        log.warning("Database restored from %s (safety backup %s)", backup_path, safety)
        return safety


def quarantine_copy(db_path: Path, quarantine_dir: Path) -> Path | None:
    """Copy a failing DB (and its WAL/SHM) aside for diagnosis. Never moves the original."""
    if not db_path.exists():
        return None
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = quarantine_dir / f"{db_path.stem}-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    for ext in ("-wal", "-shm"):
        side = Path(str(db_path) + ext)
        if side.exists():
            shutil.copy2(side, Path(str(target) + ext))
    return target


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)[:40] or "backup"
