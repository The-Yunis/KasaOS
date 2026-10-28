"""Copy the setup exe into release/<ver>/ and rewrite SHA256SUMS.txt."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kasaos.version import __version__  # noqa: E402
from scripts.package_release import sha256  # noqa: E402

out = ROOT / "release" / __version__
setup = ROOT / "dist" / f"KasaOS-Kurulum-{__version__}.exe"
shutil.copy2(setup, out / setup.name)
files = [p for p in sorted(out.iterdir()) if p.name != "SHA256SUMS.txt"]
(out / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")
print("Release finalized:", out)
