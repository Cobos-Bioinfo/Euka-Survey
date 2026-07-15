"""Tests for the version-aware DB refresh in `src.utils.ensure_latest_database`.

These cover the branch logic that lets a long-running app pick up the weekly
rebuild without a reboot, plus the safety rules (never clobber a user-provided
DB; survive a GitHub outage). Network + download are monkeypatched; a real
temp SQLite file stands in for the DB so the schema gate runs for real.
"""

import os
import sqlite3

import pytest

from src import db_version, utils
from src.constants import DB_SCHEMA_VERSION_CURRENT


def _make_valid_db(path: str, version: int = DB_SCHEMA_VERSION_CURRENT) -> None:
    """Write a minimal SQLite file stamped with a compatible schema version."""
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.commit()
    conn.close()


@pytest.fixture
def paths(tmp_path):
    return str(tmp_path / "eukaryotes.db"), str(tmp_path / "eukaryotes.db.version")


def _patch_latest(monkeypatch, tag):
    monkeypatch.setattr(
        db_version, "fetch_latest_release",
        lambda: ({"tag": tag, "date": "x", "url": "u"} if tag else None),
    )


def _no_download(monkeypatch):
    def _boom(url, dbp):
        raise AssertionError("_download_and_install should not have been called")
    monkeypatch.setattr(utils, "_download_and_install", _boom)


def test_first_run_downloads_and_records_tag(paths, monkeypatch):
    db_path, ver_path = paths
    _patch_latest(monkeypatch, "db-2026.07.06.0320")
    monkeypatch.setattr(utils, "_download_and_install", lambda url, dbp: _make_valid_db(dbp))

    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")

    assert tag == "db-2026.07.06.0320"
    assert os.path.exists(db_path)
    assert open(ver_path).read().strip() == "db-2026.07.06.0320"


def test_first_run_without_tag_records_sentinel_and_self_heals(paths, monkeypatch):
    db_path, ver_path = paths
    # API briefly unreachable while the download URL still works.
    _patch_latest(monkeypatch, None)
    monkeypatch.setattr(utils, "_download_and_install", lambda url, dbp: _make_valid_db(dbp))

    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")
    assert tag is None                                        # tag unknown this run
    assert open(ver_path).read().strip() == utils._UNKNOWN_TAG  # but marked app-managed

    # Next check: API recovers with a real tag → strictly newer than the
    # sentinel → the DB is swapped in (not frozen as a "user" DB).
    _patch_latest(monkeypatch, "db-2026.07.06.0320")
    installed = {"n": 0}

    def fake_install(url, dbp):
        installed["n"] += 1
        _make_valid_db(dbp)
    monkeypatch.setattr(utils, "_download_and_install", fake_install)

    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")
    assert installed["n"] == 1
    assert tag == "db-2026.07.06.0320"
    assert open(ver_path).read().strip() == "db-2026.07.06.0320"


def test_up_to_date_does_not_redownload(paths, monkeypatch):
    db_path, ver_path = paths
    _make_valid_db(db_path)
    open(ver_path, "w").write("db-2026.07.06.0320")
    _patch_latest(monkeypatch, "db-2026.07.06.0320")
    _no_download(monkeypatch)

    assert utils.ensure_latest_database(db_path, ver_path, "http://example/db") == "db-2026.07.06.0320"


def test_newer_release_is_swapped_in(paths, monkeypatch):
    db_path, ver_path = paths
    _make_valid_db(db_path)
    open(ver_path, "w").write("db-2026.07.01.0256")
    _patch_latest(monkeypatch, "db-2026.07.06.0320")

    installed = {"called": False}

    def fake_install(url, dbp):
        installed["called"] = True
        _make_valid_db(dbp)
    monkeypatch.setattr(utils, "_download_and_install", fake_install)

    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")

    assert installed["called"] is True
    assert tag == "db-2026.07.06.0320"
    assert open(ver_path).read().strip() == "db-2026.07.06.0320"


def test_user_db_without_sidecar_is_never_replaced(paths, monkeypatch):
    db_path, ver_path = paths
    _make_valid_db(db_path)  # a pre-existing / local build, no sidecar
    _patch_latest(monkeypatch, "db-2026.07.06.0320")
    _no_download(monkeypatch)

    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")

    assert tag is None                     # unknown version → local build
    assert not os.path.exists(ver_path)    # we didn't fabricate a version record


def test_github_unreachable_keeps_current_db(paths, monkeypatch):
    db_path, ver_path = paths
    _make_valid_db(db_path)
    open(ver_path, "w").write("db-2026.07.01.0256")
    _patch_latest(monkeypatch, None)       # fetch_latest_release() → None
    _no_download(monkeypatch)

    assert utils.ensure_latest_database(db_path, ver_path, "http://example/db") == "db-2026.07.01.0256"


def test_failed_refresh_keeps_serving_old_db(paths, monkeypatch):
    db_path, ver_path = paths
    _make_valid_db(db_path)
    open(ver_path, "w").write("db-2026.07.01.0256")
    _patch_latest(monkeypatch, "db-2026.07.06.0320")

    def failing_install(url, dbp):
        raise RuntimeError("network died mid-download")
    monkeypatch.setattr(utils, "_download_and_install", failing_install)

    # Refresh fails, but the existing DB is still valid → keep serving it.
    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")

    assert tag == "db-2026.07.01.0256"
    assert open(ver_path).read().strip() == "db-2026.07.01.0256"  # unchanged


# --- Integration: exercise the real _download_and_install (temp→validate→swap)
# with a faked HTTP source, distinguishing releases by a marker table. --------

def _make_db_with_marker(path: str, marker: str) -> None:
    _make_valid_db(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE marker (tag TEXT)")
    conn.execute("INSERT INTO marker (tag) VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _read_marker(path: str) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT tag FROM marker").fetchone()[0]
    finally:
        conn.close()


def test_real_download_first_run_then_hot_swap(paths, monkeypatch, tmp_path):
    db_path, ver_path = paths

    # Two "published" release files with distinguishable content.
    rel_old = str(tmp_path / "release_old.db")
    rel_new = str(tmp_path / "release_new.db")
    _make_db_with_marker(rel_old, "old")
    _make_db_with_marker(rel_new, "new")

    served = {"path": rel_old}  # which release the fake endpoint currently serves

    def fake_urlopen(url, timeout=None):
        return open(served["path"], "rb")  # context manager + .read() for copyfileobj
    monkeypatch.setattr(utils.urllib.request, "urlopen", fake_urlopen)

    # 1) First run: no DB → downloads the "old" release for real.
    _patch_latest(monkeypatch, "db-2026.07.01.0256")
    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")
    assert tag == "db-2026.07.01.0256"
    assert _read_marker(db_path) == "old"
    assert open(ver_path).read().strip() == "db-2026.07.01.0256"

    # 2) A newer release is published → hot-swap to the "new" file.
    served["path"] = rel_new
    _patch_latest(monkeypatch, "db-2026.07.06.0320")
    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")
    assert tag == "db-2026.07.06.0320"
    assert _read_marker(db_path) == "new"
    assert open(ver_path).read().strip() == "db-2026.07.06.0320"

    # 3) No change on a repeat call (same latest tag) → still "new", no error.
    tag = utils.ensure_latest_database(db_path, ver_path, "http://example/db")
    assert tag == "db-2026.07.06.0320"
    assert _read_marker(db_path) == "new"
