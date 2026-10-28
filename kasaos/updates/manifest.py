"""Release manifest: structure, Ed25519 signature and compatibility rules.

Trust model (docs/UPDATE_SYSTEM.md): the manifest is signed offline with a
private Ed25519 key that never touches GitHub. The application embeds the
public key(s). The manifest pins the artifact's SHA-256 and size, so a
compromised GitHub account cannot ship a modified artifact without also
producing a valid signature.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from kasaos.core.exceptions import UpdateError

MANIFEST_NAME = "kasaos-manifest.json"
SIGNATURE_NAME = "kasaos-manifest.json.sig"
MANIFEST_FORMAT = 1
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class Artifact:
    platform: str
    name: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    version: str
    notes: str
    min_app_version: str
    schema_version: int
    db_compat_floor: int
    artifacts: tuple[Artifact, ...]
    released_at: str = ""

    def artifact_for(self, platform: str) -> Artifact | None:
        return next((a for a in self.artifacts if a.platform == platform), None)


def parse_version(text: str) -> Version:
    try:
        return Version(text)
    except (InvalidVersion, TypeError):
        raise UpdateError(f"Geçersiz sürüm numarası: {text!r}") from None


def verify_signature(manifest_bytes: bytes, signature_b64: bytes, public_keys: list[str]) -> None:
    if not public_keys:
        raise UpdateError("Güncelleme imza anahtarı yapılandırılmamış; güncelleme kurulamaz.")
    try:
        sig = base64.b64decode(signature_b64.strip(), validate=True)
    except ValueError:
        raise UpdateError("Güncelleme imzası okunamadı.") from None
    for key_b64 in public_keys:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64))
        try:
            key.verify(sig, manifest_bytes)
            return
        except InvalidSignature:
            continue
    raise UpdateError("Güncelleme imzası doğrulanamadı. Dosya güvenilir kaynaktan gelmiyor olabilir.")


def sign_manifest(manifest_bytes: bytes, private_key: Ed25519PrivateKey) -> bytes:
    return base64.b64encode(private_key.sign(manifest_bytes))


def parse_manifest(data: bytes) -> Manifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise UpdateError("Güncelleme bilgisi beklenenden büyük.")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise UpdateError("Güncelleme bilgisi bozuk (JSON okunamadı).") from None
    if not isinstance(raw, dict):
        raise UpdateError("Güncelleme bilgisi geçersiz.")
    try:
        if raw["format"] != MANIFEST_FORMAT or raw["app"] != "KasaOS":
            raise UpdateError("Güncelleme bilgisi bu uygulamaya ait değil veya desteklenmeyen biçimde.")
        version = str(raw["version"])
        parse_version(version)
        min_app = str(raw["min_app_version"])
        parse_version(min_app)
        schema = int(raw["schema_version"])
        floor = int(raw["db_compat_floor"])
        arts = []
        for a in raw["artifacts"]:
            name = str(a["name"])
            sha = str(a["sha256"]).lower()
            size = int(a["size"])
            if "/" in name or "\\" in name or ".." in name or not name.endswith(".zip"):
                raise UpdateError("Güncelleme dosya adı geçersiz.")
            if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
                raise UpdateError("Güncelleme özeti (SHA-256) geçersiz.")
            if not 0 < size <= MAX_ARTIFACT_BYTES:
                raise UpdateError("Güncelleme dosya boyutu geçersiz.")
            arts.append(Artifact(str(a["platform"]), name, sha, size))
        if schema < 1 or floor < 1 or floor > schema:
            raise UpdateError("Güncelleme şema bilgisi geçersiz.")
        return Manifest(version, str(raw.get("notes", "")), min_app, schema, floor, tuple(arts),
                        str(raw.get("released_at", "")))
    except (KeyError, TypeError, ValueError) as e:
        raise UpdateError(f"Güncelleme bilgisi eksik veya hatalı: {e}") from None


def check_compatibility(m: Manifest, current_version: str, platform: str, app_schema: int) -> list[str]:
    """Return blocking problems (empty list == installable). Raises nothing."""
    problems = []
    try:
        if parse_version(m.version) <= parse_version(current_version):
            problems.append("Bu sürüm mevcut sürümden yeni değil.")
        if parse_version(current_version) < parse_version(m.min_app_version):
            problems.append(f"Bu güncelleme için önce {m.min_app_version} sürümüne geçilmelidir.")
    except UpdateError as e:
        problems.append(str(e))
    if m.artifact_for(platform) is None:
        problems.append(f"Bu sistem ({platform}) için güncelleme dosyası yok.")
    if m.schema_version < app_schema:
        problems.append("Güncelleme, mevcut veritabanı şemasından eski bir şema bekliyor.")
    return problems


def rollback_safe(m: Manifest, app_schema: int) -> bool:
    """True if the current app can still open the DB after the new version migrates it."""
    return m.db_compat_floor <= app_schema
