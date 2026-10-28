"""Single source of truth for version information.

Release tooling (scripts/make_release.py) and packaging read these values.
"""

APP_NAME = "KasaOS"
APP_TAGLINE = "Yeni Nesil İşletme Yönetimi"
APP_SPLASH_TAGLINE = "İşletmenin Kontrol Merkezi"
DEVELOPER_CREDIT = "Coded by Yunus Açıkgöz"

__version__ = "1.1.0"

# Database schema version this build writes. See docs/DATABASE.md.
SCHEMA_VERSION = 2

PLATFORM_ID = "windows-x64"
