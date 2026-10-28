"""SQLite connection management.

One connection is shared by the app and serialised with a re-entrant lock, so
services can be called from Qt worker threads without interleaving writes.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from kasaos.core.exceptions import DatabaseCorruptError, DatabaseError

log = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000


def open_connection(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
    else:
        conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


def integrity_ok(conn: sqlite3.Connection, quick: bool = True) -> tuple[bool, str]:
    try:
        rows = conn.execute("PRAGMA quick_check" if quick else "PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as e:
        return False, str(e)
    result = "; ".join(str(r[0]) for r in rows)
    return result == "ok", result


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = open_connection(self.path)
            ok, detail = integrity_ok(conn)
        except sqlite3.DatabaseError as e:
            raise DatabaseCorruptError(f"Veritabanı açılamadı: {e}") from e
        if not ok:
            conn.close()
            raise DatabaseCorruptError(f"Veritabanı bütünlük kontrolü başarısız: {detail}")
        try:
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            conn.execute("PRAGMA synchronous = FULL")
        except sqlite3.DatabaseError as e:
            conn.close()
            raise DatabaseError(f"Veritabanı yapılandırılamadı: {e}") from e
        log.info("Database opened at %s (journal_mode=%s)", self.path, mode)
        self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.DatabaseError:
                    log.warning("WAL checkpoint failed during close", exc_info=True)
                self._conn.close()
                self._conn = None
                log.info("Database closed")

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("Veritabanı açık değil.")
        return self._conn

    @contextmanager
    def read(self):
        with self._lock:
            yield self.conn

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception."""
        with self._lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
