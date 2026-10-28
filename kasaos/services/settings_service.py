"""Typed access to the settings table."""

from __future__ import annotations

from kasaos.config import DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPO
from kasaos.infrastructure.database import repositories as repo
from kasaos.infrastructure.database.connection import Database

DEFAULTS: dict[str, str] = {
    "business_name": "",
    "update_owner": DEFAULT_GITHUB_OWNER,
    "update_repo": DEFAULT_GITHUB_REPO,
    "update_check_on_start": "1",
    "update_allow_prerelease": "0",
    "auto_backup_on_start": "1",
    "auto_backup_keep": "30",
    "default_income_method": "",
    "default_expense_method": "",
}


class SettingsService:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> str:
        with self.db.read() as c:
            value = repo.get_setting(c, key)
        return DEFAULTS.get(key, "") if value is None else value

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "1"

    def get_int(self, key: str, fallback: int = 0) -> int:
        try:
            return int(self.get(key))
        except ValueError:
            return fallback

    def set(self, key: str, value: str | bool | int) -> None:
        if isinstance(value, bool):
            value = "1" if value else "0"
        with self.db.transaction() as c:
            repo.set_setting(c, key, str(value))

    def set_many(self, values: dict[str, str | bool | int]) -> None:
        with self.db.transaction() as c:
            for key, value in values.items():
                if isinstance(value, bool):
                    value = "1" if value else "0"
                repo.set_setting(c, key, str(value))
