"""Explicit construction of the service graph (no global mutable state)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from kasaos.config import AppPaths
from kasaos.infrastructure.database.connection import Database
from kasaos.infrastructure.database.migrations import migrate
from kasaos.services.backup_service import BackupService
from kasaos.services.cash_service import CashService
from kasaos.services.catalog_service import CatalogService
from kasaos.services.reporting_service import ReportingService
from kasaos.services.settings_service import SettingsService
from kasaos.services.transaction_service import TransactionService
from kasaos.version import SCHEMA_VERSION

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    transactions: TransactionService
    catalog: CatalogService
    cash: CashService
    reports: ReportingService
    backups: BackupService
    settings: SettingsService
    schema_version: int = 0
    startup_notes: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, paths: AppPaths) -> "AppContext":
        db = Database(paths.database)
        return cls(paths=paths, db=db, transactions=TransactionService(db), catalog=CatalogService(db),
                   cash=CashService(db), reports=ReportingService(db),
                   backups=BackupService(db, paths.backups_dir, paths.quarantine_dir),
                   settings=SettingsService(db))

    def open_database(self) -> None:
        """Open + migrate. Raises DatabaseError subclasses; never deletes data."""
        self.db.open()
        self.schema_version = migrate(self.db, SCHEMA_VERSION, lambda reason: self.backups.create(reason))

    def reopen_database(self) -> None:
        self.db.close()
        self.open_database()

    def auto_backup(self) -> None:
        if not self.settings.get_bool("auto_backup_on_start"):
            return
        self.backups.create("auto")
        self.backups.prune(keep=self.settings.get_int("auto_backup_keep", 30))

    def shutdown(self) -> None:
        self.db.close()
