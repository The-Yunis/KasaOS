"""Application exception hierarchy. Messages are user-facing Turkish text."""


class KasaOSError(Exception):
    """Base class for expected, user-reportable errors."""


class ValidationError(KasaOSError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class NotFoundError(KasaOSError):
    pass


class DatabaseError(KasaOSError):
    pass


class DatabaseCorruptError(DatabaseError):
    pass


class IncompatibleDatabaseError(DatabaseError):
    pass


class MigrationError(DatabaseError):
    def __init__(self, message: str, backup_path=None):
        super().__init__(message)
        self.backup_path = backup_path


class BackupError(KasaOSError):
    pass


class UpdateError(KasaOSError):
    pass
