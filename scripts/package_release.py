"""Create release/<ver>/: update artifact zip, installer bundle, unsigned manifest, checksums.

Signing is a separate, deliberate step (scripts/sign_manifest.py) performed on a
machine that holds the private key.
"""

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kasaos.updates.install_state import APP_EXE, VERSION_FILE  # noqa: E402
from kasaos.updates.manifest import MANIFEST_NAME  # noqa: E402
from kasaos.version import PLATFORM_ID, SCHEMA_VERSION, __version__  # noqa: E402
from kasaos.infrastructure.database.migrations import MIGRATIONS  # noqa: E402

MIN_APP_VERSION = "1.0.0"  # oldest version allowed to update directly to this one


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src: Path, dest: Path, prefix: str = "") -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, prefix + f.relative_to(src).as_posix())


def main():
    app_dir = ROOT / "dist" / "KasaOS-app"
    launcher = ROOT / "dist" / "KasaOS.exe"
    if not (app_dir / APP_EXE).is_file() or not launcher.is_file():
        sys.exit("dist/ is incomplete; run scripts/build.ps1")
    marker = (app_dir / VERSION_FILE).read_text(encoding="ascii").strip()
    if marker != __version__:
        sys.exit(f"version marker {marker} != {__version__}")

    out = ROOT / "release" / __version__
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    artifact = out / f"KasaOS-{__version__}-{PLATFORM_ID}.zip"
    zip_dir(app_dir, artifact)

    # Installer bundle: launcher + app + install script (per-user, no admin).
    bundle_src = ROOT / "build" / "bundle"
    if bundle_src.exists():
        shutil.rmtree(bundle_src)
    (bundle_src / "app").mkdir(parents=True)
    shutil.copy2(launcher, bundle_src / "KasaOS.exe")
    shutil.copytree(app_dir, bundle_src / "app", dirs_exist_ok=True)
    shutil.copy2(ROOT / "packaging" / "install.ps1", bundle_src / "install.ps1")
    shutil.copy2(ROOT / "packaging" / "KURULUM.txt", bundle_src / "KURULUM.txt")
    setup = out / f"KasaOS-{__version__}-{PLATFORM_ID}-kurulum.zip"
    zip_dir(bundle_src, setup)

    floor = max(m.compat_floor for m in MIGRATIONS)
    manifest = {
        "format": 1, "app": "KasaOS", "version": __version__,
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": _notes(), "min_app_version": MIN_APP_VERSION,
        "schema_version": SCHEMA_VERSION, "db_compat_floor": floor,
        "artifacts": [{"platform": PLATFORM_ID, "name": artifact.name, "sha256": sha256(artifact),
                       "size": artifact.stat().st_size}],
    }
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    sums = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(out.iterdir()))
    (out / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    print(f"Release files in {out}\nNext: python scripts/sign_manifest.py {out / MANIFEST_NAME} --key <private.pem>")


def _notes() -> str:
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.exists():
        return ""
    text = changelog.read_text(encoding="utf-8")
    start = text.find(f"## [{__version__}]")
    if start < 0:
        return ""
    end = text.find("\n## [", start + 5)
    return text[start:end if end > 0 else None].strip()


if __name__ == "__main__":
    main()
