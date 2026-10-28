"""Check what actually got packaged into dist/KasaOS-app/KasaOS-app.exe.

Release 1.0.0 shipped with an empty TRUSTED_PUBLIC_KEYS although the source had a
key, so those installs can never verify an update. This check reads the frozen
modules back out of the built executable and fails the build unless the trusted
keys, version and update source match the source tree.
"""

import marshal
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kasaos.config import DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPO  # noqa: E402
from kasaos.updates.trust import TRUSTED_PUBLIC_KEYS  # noqa: E402
from kasaos.version import __version__  # noqa: E402


def frozen_consts(pyz, module: str) -> list:
    code = pyz.extract(module)
    if isinstance(code, bytes):
        code = marshal.loads(code)
    return list(code.co_consts)


def main(exe: Path) -> int:
    pyz = CArchiveReader(str(exe)).open_embedded_archive("PYZ.pyz")
    errors = []
    trust = frozen_consts(pyz, "kasaos.updates.trust")
    missing = [k for k in TRUSTED_PUBLIC_KEYS if k not in trust]
    if not TRUSTED_PUBLIC_KEYS:
        errors.append("source has no TRUSTED_PUBLIC_KEYS")
    if missing:
        errors.append(f"trusted keys missing from the built exe: {missing}")
    if __version__ not in frozen_consts(pyz, "kasaos.version"):
        errors.append(f"built exe does not carry version {__version__}")
    cfg = frozen_consts(pyz, "kasaos.config")
    if DEFAULT_GITHUB_OWNER not in cfg or DEFAULT_GITHUB_REPO not in cfg:
        errors.append("update source (owner/repo) missing from the built exe")
    if errors:
        print("BUILD VERIFICATION FAILED:\n  " + "\n  ".join(errors))
        return 1
    print(f"Build verified: {__version__}, {len(TRUSTED_PUBLIC_KEYS)} trusted key(s), "
          f"{DEFAULT_GITHUB_OWNER}/{DEFAULT_GITHUB_REPO}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "KasaOS-app" / "KasaOS-app.exe"))
