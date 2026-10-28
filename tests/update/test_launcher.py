"""Launcher trial / rollback behaviour with real child processes."""

import json
import sys
from pathlib import Path

import pytest

from kasaos.updates.install_state import InstallState
from kasaos.updates.launcher_core import Launcher, request_update

FAKE = Path(__file__).with_name("fake_app.py")


def make_version(root: Path, version: str, behaviour: str = "ready") -> Path:
    d = root / "versions" / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "KasaOS-app.exe").write_bytes(b"stub")
    (d / "kasaos-version.txt").write_text(version, encoding="utf-8")
    (d / "behaviour.txt").write_text(behaviour, encoding="utf-8")
    return d


def launcher(root: Path, timeout=8.0) -> Launcher:
    return Launcher(root, command_for=lambda vdir: [sys.executable, str(FAKE), str(vdir)], ready_timeout=timeout)


def launches(root: Path) -> list[dict]:
    p = root / "launches.log"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def finish(outcome):
    # let the fake app record its launch and exit by itself (it idles ~1 s)
    if outcome.process is not None:
        outcome.process.wait(20)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "install"
    make_version(r, "1.0.0")
    st = InstallState(current="1.0.0")
    st.save(r)
    return r


def test_normal_start(root):
    out = launcher(root).run()
    finish(out)
    assert out.status == "started" and out.version == "1.0.0"
    assert launches(root)[0]["ready_file"] is False


def test_successful_update_switches_after_ready(root):
    make_version(root, "1.1.0", "ready")
    request_update(root, "1.1.0")
    out = launcher(root).run()
    finish(out)
    assert out.status == "updated"
    st = InstallState.load(root)
    assert (st.current, st.previous, st.pending, st.attempt) == ("1.1.0", "1.0.0", None, None)
    assert st.last_result["status"] == "success"
    assert (root / "versions" / "1.0.0").exists()  # previous kept for recovery


@pytest.mark.parametrize("behaviour,fragment", [
    ("crash", "kapandı"), ("hang", "hazır sinyali vermedi"), ("wrong", "yanlış sürüm")])
def test_failed_candidate_rolls_back(root, behaviour, fragment):
    make_version(root, "1.1.0", behaviour)
    request_update(root, "1.1.0")
    out = launcher(root, timeout=3).run()
    finish(out)
    assert out.status == "rolled_back" and out.version == "1.0.0"
    st = InstallState.load(root)
    assert st.current == "1.0.0" and st.pending is None and st.attempt is None
    assert fragment in st.failed["1.1.0"]
    runs = launches(root)
    assert [r["version"] for r in runs] == ["1.1.0", "1.0.0"]
    notice = json.loads(runs[-1]["notice"])
    assert notice["status"] == "rolled_back"


def test_failed_release_not_retried_automatically(root):
    make_version(root, "1.1.0", "crash")
    request_update(root, "1.1.0")
    finish(launcher(root, timeout=3).run())
    # something marks it pending again without an explicit retry
    st = InstallState.load(root)
    st.pending = "1.1.0"
    st.save(root)
    out = launcher(root).run()
    finish(out)
    assert out.status == "started" and out.version == "1.0.0"
    assert [r["version"] for r in launches(root)] == ["1.1.0", "1.0.0", "1.0.0"]


def test_explicit_retry_after_fix(root):
    make_version(root, "1.1.0", "crash")
    request_update(root, "1.1.0")
    finish(launcher(root, timeout=3).run())
    make_version(root, "1.1.0", "ready")
    request_update(root, "1.1.0")  # user pressed "tekrar dene"
    out = launcher(root).run()
    finish(out)
    assert out.status == "updated"


def test_interrupted_attempt_is_treated_as_failure_no_loop(root):
    make_version(root, "1.1.0", "ready")
    st = InstallState.load(root)
    st.attempt = {"version": "1.1.0", "from": "1.0.0", "started_at": "x"}
    st.save(root)
    out = launcher(root).run()
    finish(out)
    assert out.status == "started" and out.version == "1.0.0"
    st = InstallState.load(root)
    assert "1.1.0" in st.failed and st.attempt is None


def test_incomplete_pending_is_rejected(root):
    d = make_version(root, "1.1.0")
    (d / "KasaOS-app.exe").unlink()
    st = InstallState.load(root)
    st.pending = "1.1.0"
    st.save(root)
    out = launcher(root).run()
    finish(out)
    assert out.version == "1.0.0"
    assert "1.1.0" in InstallState.load(root).failed


def test_missing_current_falls_back_to_previous(root):
    make_version(root, "0.9.0")
    st = InstallState(current="1.0.0", previous="0.9.0")
    st.save(root)
    (root / "versions" / "1.0.0" / "KasaOS-app.exe").unlink()
    out = launcher(root).run()
    finish(out)
    assert out.version == "0.9.0"


def test_corrupt_state_file_recovers(root):
    (root / "install_state.json").write_text("{not json", encoding="utf-8")
    out = launcher(root).run()
    finish(out)
    assert out.status == "started" and out.version == "1.0.0"


def test_prune_keeps_current_and_previous(root):
    make_version(root, "0.9.0")
    make_version(root, "1.1.0")
    request_update(root, "1.1.0")
    finish(launcher(root).run())
    assert sorted(p.name for p in (root / "versions").iterdir()) == ["1.0.0", "1.1.0"]


def test_user_data_untouched_by_failed_update(root, tmp_path):
    data = tmp_path / "home" / "data" / "kasaos.db"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"precious")
    make_version(root, "1.1.0", "crash")
    request_update(root, "1.1.0")
    finish(launcher(root, timeout=3).run())
    assert data.read_bytes() == b"precious"
