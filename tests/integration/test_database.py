import sqlite3
from datetime import date

import pytest

from kasaos.core.application_context import AppContext
from kasaos.core.exceptions import (BackupError, DatabaseCorruptError, IncompatibleDatabaseError,
                                    MigrationError)
from kasaos.domain.entities import TransactionFilter
from kasaos.infrastructure.database.connection import Database
from kasaos.infrastructure.database.migrations import MIGRATIONS, Migration, current_schema, migrate
from kasaos.services.backup_service import verify_backup
from kasaos.version import SCHEMA_VERSION as S

NEXT = S + 1


def test_persistence_after_restart(paths, h, ctx):
    t = h.income(123_45)
    ctx.shutdown()
    ctx2 = AppContext.build(paths)
    ctx2.open_database()
    try:
        got = ctx2.transactions.get(t.id)
        assert got is not None and got.amount == 123_45
    finally:
        ctx2.shutdown()


def test_pragmas(ctx):
    c = ctx.db.conn
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_transaction_rollback_on_error(ctx, h):
    with pytest.raises(RuntimeError):
        with ctx.db.transaction() as c:
            c.execute("UPDATE settings SET value='x'")
            c.execute("INSERT INTO settings(key, value) VALUES ('probe','1')")
            raise RuntimeError("boom")
    assert ctx.settings.get("probe") == ""


def _extra_migration(fail: bool):
    def apply(c):
        c.execute("ALTER TABLE transactions ADD COLUMN receipt_no TEXT NOT NULL DEFAULT ''")
        if fail:
            raise RuntimeError("simulated failure")
    return MIGRATIONS + [Migration(NEXT, "fiş no", apply, compat_floor=1)]


def test_migration_success_creates_backup(ctx, h, paths):
    h.income(10_00)
    v = migrate(ctx.db, NEXT, ctx.backups.create, _extra_migration(False))
    assert v == NEXT
    backups = ctx.backups.list()
    assert any(b.reason.startswith(f"pre-migration-v{S}-to-v{NEXT}") for b in backups)
    assert verify_backup(backups[0].path) == S
    assert len(ctx.transactions.list(TransactionFilter())) == 1


def test_failed_migration_rolls_back_and_preserves_data(ctx, h):
    t = h.income(10_00)
    with pytest.raises(MigrationError) as ei:
        migrate(ctx.db, NEXT, ctx.backups.create, _extra_migration(True))
    assert ei.value.backup_path is not None and ei.value.backup_path.exists()
    assert current_schema(ctx.db.conn) == S
    cols = [r[1] for r in ctx.db.conn.execute("PRAGMA table_info(transactions)")]
    assert "receipt_no" not in cols
    assert ctx.transactions.get(t.id).amount == 10_00


def test_old_app_can_open_expanded_schema(ctx):
    migrate(ctx.db, NEXT, ctx.backups.create, _extra_migration(False))
    assert migrate(ctx.db, S, ctx.backups.create) == NEXT  # compat_floor 1 → allowed


def test_old_app_rejects_incompatible_schema(ctx):
    with ctx.db.transaction() as c:
        c.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
        c.execute("UPDATE meta SET value='4' WHERE key='compat_floor'")
    with pytest.raises(IncompatibleDatabaseError):
        migrate(ctx.db, S, ctx.backups.create)


def test_foreign_db_rejected(tmp_path):
    p = tmp_path / "other.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE stuff(x)")
    c.commit()
    c.close()
    db = Database(p)
    db.open()
    with pytest.raises(IncompatibleDatabaseError):
        migrate(db, 1, None)
    db.close()
    assert p.exists()


def test_corrupt_database_detected_not_deleted(tmp_path):
    p = tmp_path / "bad.db"
    p.write_bytes(b"SQLite format 3\x00" + b"\x13" * 4096)
    db = Database(p)
    with pytest.raises(DatabaseCorruptError):
        db.open()
    assert p.exists() and p.stat().st_size > 4000


def test_backup_and_restore_roundtrip(ctx, h, paths):
    t1 = h.income(100_00)
    backup = ctx.backups.create("manual")
    t2 = h.income(999_00)
    safety = ctx.backups.restore(backup, S)
    ctx.open_database()
    assert ctx.transactions.get(t1.id) is not None
    assert ctx.transactions.get(t2.id) is None
    # the pre-restore safety backup contains the newer record
    assert verify_backup(safety) == S
    probe = sqlite3.connect(safety)
    assert probe.execute("SELECT count(*) FROM transactions WHERE id=?", (t2.id,)).fetchone()[0] == 1
    probe.close()


def test_corrupted_backup_rejected_and_live_db_untouched(ctx, h, tmp_path):
    t = h.income(50_00)
    good = ctx.backups.create("manual")
    bad = tmp_path / "bad.kasaosbak"
    data = bytearray(good.read_bytes())
    data[100:4096] = b"\xff" * 3996  # page-1 b-tree header + cell pointers: always real corruption
    bad.write_bytes(bytes(data))
    with pytest.raises(BackupError):
        ctx.backups.restore(bad, S)
    trunc = tmp_path / "trunc.kasaosbak"
    trunc.write_bytes(good.read_bytes()[:1000])
    with pytest.raises(BackupError):
        ctx.backups.restore(trunc, S)
    notdb = tmp_path / "x.kasaosbak"
    notdb.write_text("hello")
    with pytest.raises(BackupError):
        verify_backup(notdb)
    assert ctx.transactions.get(t.id) is not None


def test_restore_when_live_db_is_corrupt(ctx, h, paths):
    t = h.income(70_00)
    good = ctx.backups.create("manual")
    ctx.shutdown()
    paths.database.write_bytes(b"SQLite format 3\x00" + b"\x13" * 8192)
    ctx2 = AppContext.build(paths)
    with pytest.raises(DatabaseCorruptError):
        ctx2.open_database()
    safety = ctx2.backups.restore(good, S)
    assert safety is not None and safety.parent == paths.quarantine_dir
    assert safety.read_bytes().startswith(b"SQLite format 3\x00\x13")  # broken original preserved
    ctx2.open_database()
    try:
        assert ctx2.transactions.get(t.id).amount == 70_00
    finally:
        ctx2.shutdown()


def test_backup_from_newer_schema_rejected(ctx):
    b = ctx.backups.create("manual")
    c = sqlite3.connect(b)
    c.execute("UPDATE meta SET value='9' WHERE key='schema_version'")
    c.commit()
    c.close()
    with pytest.raises(BackupError):
        ctx.backups.restore(b, S)


def test_prune_keeps_manual(ctx):
    for _ in range(4):
        ctx.backups.create("auto")
    ctx.backups.create("manual")
    ctx.backups.prune(keep=2)
    reasons = sorted(b.reason for b in ctx.backups.list())
    assert reasons == ["auto", "auto", "manual"]


def test_uncommitted_write_lost_committed_kept(paths, h, ctx):
    """Simulate a crash mid-transaction: committed rows survive, open ones vanish."""
    t = h.income(10_00)
    ctx.db.conn.execute("BEGIN IMMEDIATE")
    ctx.db.conn.execute("UPDATE transactions SET amount=1 WHERE id=?", (t.id,))
    # crash: the connection disappears without commit
    ctx.db._conn.close()
    ctx.db._conn = None
    ctx2 = AppContext.build(paths)
    ctx2.open_database()
    try:
        assert ctx2.transactions.get(t.id).amount == 10_00
    finally:
        ctx2.shutdown()


def test_csv_export(ctx, h, tmp_path):
    h.income(1_250_50)
    out = tmp_path / "rapor.csv"
    assert ctx.reports.export_csv(out, None, date.today()) == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "1.250,50" in text and "Gelir" in text


def test_upgrade_real_v1_database_to_v2(paths):
    """A 1.0.0 database with data opens in 1.1.0: backup first, data kept, personnel tables added."""
    from kasaos.infrastructure.database.migrations import MIGRATIONS as ALL
    db = Database(paths.database)
    db.open()
    migrate(db, 1, None, [m for m in ALL if m.version == 1])
    with db.transaction() as c:
        c.execute("INSERT INTO transactions(id, kind, occurred_on, amount, account_id, category_id, "
                  "payment_method_id, created_at, updated_at) VALUES ('old','income','2026-10-01',5000,1,1,1,'x','x')")
    db.close()

    ctx = AppContext.build(paths)
    ctx.open_database()
    try:
        assert ctx.schema_version == 2
        assert ctx.transactions.get("old").amount == 5000
        assert any(b.reason == "pre-migration-v1-to-v2" and b.schema_version == 1 for b in ctx.backups.list())
        assert ctx.employees.employees() == []
        # rollback safety: the 1.0.0 app (schema 1) may still open the migrated DB
        assert migrate(ctx.db, 1, None) == 2
    finally:
        ctx.shutdown()
