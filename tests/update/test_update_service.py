"""Update discovery, verification and staging against a mocked GitHub."""

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kasaos.core.exceptions import UpdateError
from kasaos.services.update_service import UpdateService
from kasaos.updates import manifest as mf
from kasaos.updates.github_client import GitHubReleaseClient, Response
from kasaos.updates.install_state import InstallState
from kasaos.updates.stager import stage_artifact

PLATFORM = "windows-x64"


def keypair():
    k = Ed25519PrivateKey.generate()
    pub = base64.b64encode(k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return k, pub


def make_zip(version: str, extra: dict[str, bytes] | None = None, version_text: str | None = None,
             omit_exe=False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if not omit_exe:
            z.writestr("KasaOS-app.exe", b"MZ fake exe")
        z.writestr("kasaos-version.txt", version_text or version)
        z.writestr("_internal/lib.dll", b"x" * 100)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


def make_manifest(version: str, artifact: bytes, **over) -> bytes:
    m = {"format": 1, "app": "KasaOS", "version": version, "notes": "Yenilikler", "min_app_version": "1.0.0",
         "schema_version": 1, "db_compat_floor": 1, "released_at": "2026-10-01",
         "artifacts": [{"platform": PLATFORM, "name": f"KasaOS-{version}-{PLATFORM}.zip",
                        "sha256": hashlib.sha256(artifact).hexdigest(), "size": len(artifact)}]}
    m.update(over)
    return json.dumps(m).encode()


class FakeGitHub:
    """Serves /releases and asset downloads from memory."""

    def __init__(self):
        self.releases = []
        self.files: dict[str, bytes] = {}
        self.status_override = None
        self.raise_error = None
        self.truncate = {}

    def add_release(self, tag, assets: dict[str, bytes], prerelease=False, draft=False):
        entry = {"tag_name": tag, "name": tag, "body": "notes", "draft": draft, "prerelease": prerelease,
                 "assets": []}
        for name, data in assets.items():
            url = f"https://github.com/o/r/releases/download/{tag}/{name}"
            self.files[url] = data
            entry["assets"].append({"name": name, "browser_download_url": url, "size": len(data)})
        self.releases.append(entry)

    def get(self, url, timeout, headers):
        if self.raise_error:
            raise self.raise_error
        if url.startswith("https://api.github.com"):
            if self.status_override:
                return Response(self.status_override[0], self.status_override[1], io.BytesIO(b"{}"))
            return Response(200, {}, io.BytesIO(json.dumps(self.releases).encode()))
        if url not in self.files:
            return Response(404, {}, io.BytesIO(b""))
        data = self.files[url]
        if url in self.truncate:
            data = data[: self.truncate[url]]
        return Response(200, {}, io.BytesIO(data))


@pytest.fixture
def env(tmp_path):
    key, pub = keypair()
    gh = FakeGitHub()
    root = tmp_path / "install"
    (root / "versions" / "1.0.0").mkdir(parents=True)
    (root / "versions" / "1.0.0" / "KasaOS-app.exe").write_bytes(b"old")
    (root / "versions" / "1.0.0" / "kasaos-version.txt").write_text("1.0.0")
    InstallState(current="1.0.0").save(root)
    backups = []

    def service(install_root=root, keys=None):
        return UpdateService(
            current_version="1.0.0", app_schema=1, platform=PLATFORM, updates_dir=tmp_path / "updates",
            install_root=install_root, public_keys=[pub] if keys is None else keys,
            source=lambda: ("o", "r", False),
            client_factory=lambda o, r: GitHubReleaseClient(o, r, transport=gh),
            backup_fn=lambda reason: backups.append(reason))

    def publish(version, artifact=None, manifest=None, sign_with=None, tag=None, **kw):
        artifact = artifact if artifact is not None else make_zip(version)
        manifest = manifest if manifest is not None else make_manifest(version, artifact)
        sig = mf.sign_manifest(manifest, sign_with or key)
        gh.add_release(tag or f"v{version}", {f"KasaOS-{version}-{PLATFORM}.zip": artifact,
                                               mf.MANIFEST_NAME: manifest, mf.SIGNATURE_NAME: sig}, **kw)

    class E:
        pass
    e = E()
    e.gh, e.root, e.service, e.publish, e.backups, e.key, e.pub = gh, root, service, publish, backups, key, pub
    return e


def test_no_update_available(env):
    env.publish("1.0.0")
    assert env.service().check().status == "none"


def test_not_configured():
    s = UpdateService(current_version="1.0.0", app_schema=1, platform=PLATFORM, updates_dir=Path("."),
                      install_root=None, public_keys=[], source=lambda: ("", "", False))
    assert s.check().status == "not_configured"


def test_compatible_update_full_flow(env):
    env.publish("1.1.0")
    s = env.service()
    chk = s.check()
    assert chk.status == "available" and chk.manifest.version == "1.1.0" and chk.rollback_safe
    stages = []
    assert s.prepare(chk, lambda st, d, t: stages.append(st)) == "1.1.0"
    st = InstallState.load(env.root)
    assert st.pending == "1.1.0" and st.current == "1.0.0"
    assert (env.root / "versions" / "1.1.0" / "KasaOS-app.exe").exists()
    assert (env.root / "versions" / "1.0.0" / "KasaOS-app.exe").read_bytes() == b"old"
    assert env.backups == ["pre-update-1.1.0"]
    assert stages[0] == "download" and stages[-1] == "ready"


def test_picks_newest_and_ignores_prerelease_and_draft(env):
    env.publish("1.1.0")
    env.publish("1.3.0", prerelease=True)
    env.publish("1.4.0", draft=True)
    env.publish("1.2.0")
    assert env.service().check().manifest.version == "1.2.0"


def test_network_errors_are_reported_not_raised(env):
    env.gh.raise_error = UpdateError("Güncelleme sunucusuna ulaşılamadı: timed out")
    r = env.service().check()
    assert r.status == "error" and "ulaşılamadı" in r.message


def test_rate_limit(env):
    env.gh.status_override = (403, {"x-ratelimit-remaining": "0"})
    r = env.service().check()
    assert r.status == "error" and "sınır" in r.message


def test_malformed_github_response(env):
    env.gh.releases = {"not": "a list"}
    assert env.service().check().status == "error"


def test_missing_manifest_or_artifact(env):
    env.gh.add_release("v1.1.0", {"KasaOS-1.1.0-windows-x64.zip": b"zip"})
    r = env.service().check()
    assert r.status == "none" and "imzalı" in r.skipped[0]


def test_missing_artifact_asset_rejected_at_prepare(env):
    art = make_zip("1.1.0")
    m = make_manifest("1.1.0", art)
    env.gh.add_release("v1.1.0", {mf.MANIFEST_NAME: m, mf.SIGNATURE_NAME: mf.sign_manifest(m, env.key)})
    s = env.service()
    with pytest.raises(UpdateError, match="bulunamadı"):
        s.prepare(s.check())
    assert InstallState.load(env.root).pending is None


def test_invalid_signature_rejected(env):
    other, _ = keypair()
    env.publish("1.1.0", sign_with=other)
    r = env.service().check()
    assert r.status == "none" and "imza" in r.skipped[0].lower()


def test_no_trusted_keys_rejects_everything(env):
    env.publish("1.1.0")
    r = env.service(keys=[]).check()
    assert r.status == "none" and "anahtar" in r.skipped[0]


def test_tampered_manifest_rejected(env):
    art = make_zip("1.1.0")
    m = make_manifest("1.1.0", art)
    sig = mf.sign_manifest(m, env.key)
    tampered = m.replace(b"Yenilikler", b"YenilikleR")
    env.gh.add_release("v1.1.0", {"KasaOS-1.1.0-windows-x64.zip": art, mf.MANIFEST_NAME: tampered,
                                  mf.SIGNATURE_NAME: sig})
    assert env.service().check().status == "none"


def test_checksum_mismatch_rejected(env):
    good = make_zip("1.1.0")
    m = make_manifest("1.1.0", good)
    evil = bytearray(good)
    evil[-30] ^= 0xFF
    sig = mf.sign_manifest(m, env.key)
    env.gh.add_release("v1.1.0", {"KasaOS-1.1.0-windows-x64.zip": bytes(evil), mf.MANIFEST_NAME: m,
                                  mf.SIGNATURE_NAME: sig})
    s = env.service()
    with pytest.raises(UpdateError, match="SHA-256"):
        s.prepare(s.check())
    assert not (env.root / "versions" / "1.1.0").exists()
    assert InstallState.load(env.root).pending is None


def test_incomplete_download_rejected(env):
    env.publish("1.1.0")
    url = next(u for u in env.gh.files if u.endswith(".zip"))
    env.gh.truncate[url] = 50
    s = env.service()
    with pytest.raises(UpdateError, match="eksik"):
        s.prepare(s.check())
    assert not list((env.root / "versions").glob("1.1.0*"))


def test_incompatible_platform_and_min_version(env):
    art = make_zip("1.1.0")
    env.publish("1.1.0", manifest=make_manifest("1.1.0", art, min_app_version="1.0.5"), artifact=art)
    art2 = make_zip("1.2.0")
    m2 = json.loads(make_manifest("1.2.0", art2))
    m2["artifacts"][0]["platform"] = "linux-arm64"
    env.publish("1.2.0", manifest=json.dumps(m2).encode(), artifact=art2)
    r = env.service().check()
    assert r.status == "none" and len(r.skipped) == 2


def test_tag_manifest_version_mismatch(env):
    art = make_zip("1.1.0")
    env.publish("1.1.0", artifact=art, manifest=make_manifest("1.1.0", art), tag="v1.5.0")
    assert env.service().check().status == "none"


def test_database_compatibility_flagged(env):
    art = make_zip("2.0.0")
    env.publish("2.0.0", artifact=art, manifest=make_manifest("2.0.0", art, schema_version=3, db_compat_floor=3))
    r = env.service().check()
    assert r.status == "available" and r.rollback_safe is False


def test_corrupt_archive_rejected(env):
    art = b"PK\x03\x04 this is not a zip at all" * 10
    env.publish("1.1.0", artifact=art)
    s = env.service()
    with pytest.raises(UpdateError, match="bozuk"):
        s.prepare(s.check())
    assert not (env.root / "versions" / "1.1.0").exists()


@pytest.mark.parametrize("bad", ["../evil.txt", "/abs.txt", "C:/win.txt", "a/../../b.txt"])
def test_path_traversal_rejected(tmp_path, bad):
    z = tmp_path / "a.zip"
    z.write_bytes(make_zip("1.1.0", extra={bad: b"x"}))
    with pytest.raises(UpdateError, match="güvenli olmayan"):
        stage_artifact(z, tmp_path / "root", "1.1.0")
    assert not (tmp_path / "evil.txt").exists()
    assert not list((tmp_path / "root" / "versions").iterdir())


def test_symlink_entry_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("KasaOS-app.exe", b"MZ")
        zf.writestr("kasaos-version.txt", "1.1.0")
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "../../etc/passwd")
    z = tmp_path / "a.zip"
    z.write_bytes(buf.getvalue())
    with pytest.raises(UpdateError, match="sembolik"):
        stage_artifact(z, tmp_path / "root", "1.1.0")


def test_wrong_version_inside_archive_rejected(env):
    art = make_zip("1.1.0", version_text="1.0.9")
    env.publish("1.1.0", artifact=art)
    s = env.service()
    with pytest.raises(UpdateError, match="uyuşmuyor"):
        s.prepare(s.check())


def test_missing_exe_in_archive_rejected(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(make_zip("1.1.0", omit_exe=True))
    with pytest.raises(UpdateError, match="eksik"):
        stage_artifact(z, tmp_path / "root", "1.1.0")


def test_interrupted_staging_leaves_no_partial_version(env, monkeypatch):
    env.publish("1.1.0")
    s = env.service()
    chk = s.check()
    import shutil as _sh
    calls = {"n": 0}
    real = _sh.copyfileobj

    def flaky(src, dst, length=0):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(src, dst, length)
    monkeypatch.setattr("kasaos.updates.stager.shutil.copyfileobj", flaky)
    with pytest.raises(UpdateError):
        s.prepare(chk)
    assert not list((env.root / "versions").glob("*1.1.0*"))
    assert InstallState.load(env.root).pending is None
    monkeypatch.setattr("kasaos.updates.stager.shutil.copyfileobj", real)
    assert s.prepare(chk) == "1.1.0"  # retry works, cached artifact re-verified


def test_dev_mode_cannot_install(env):
    env.publish("1.1.0")
    s = env.service(install_root=None)
    with pytest.raises(UpdateError, match="desteklemiyor"):
        s.prepare(s.check())


def test_previously_failed_version_is_flagged(env):
    env.publish("1.1.0")
    st = InstallState.load(env.root)
    st.failed["1.1.0"] = "kapandı"
    st.save(env.root)
    assert env.service().check().previously_failed == "kapandı"


def test_insecure_download_host_rejected(env):
    art = make_zip("1.1.0")
    m = make_manifest("1.1.0", art)
    env.gh.releases.append({"tag_name": "v1.1.0", "draft": False, "prerelease": False, "assets": [
        {"name": mf.MANIFEST_NAME, "browser_download_url": "https://evil.example.com/m.json", "size": 1},
        {"name": mf.SIGNATURE_NAME, "browser_download_url": "https://evil.example.com/m.sig", "size": 1}]})
    r = env.service().check()
    assert r.status == "none" and "beklenmeyen" in r.skipped[0]


@pytest.mark.parametrize("data", [b"", b"[]", b"{\"format\": 1}", b"\xff\xfe", b'{"format":1,"app":"Other"}'])
def test_malformed_manifest(data):
    with pytest.raises(UpdateError):
        mf.parse_manifest(data)
