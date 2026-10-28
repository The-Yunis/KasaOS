"""Zip build/bundle (launcher + app) into build/payload.zip for the setup exe."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.package_release import zip_dir  # noqa: E402

bundle = ROOT / "build" / "bundle"
zip_dir(bundle, ROOT / "build" / "payload.zip")
print("payload.zip written")
