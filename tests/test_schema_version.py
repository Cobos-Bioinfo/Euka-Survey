"""Tests for the `PRAGMA user_version` schema-version gate.

Pairs with `src/utils.py::ensure_latest_database` (which calls
`_check_schema_version`) and the pipeline's `_stamp_schema_version`
step in `db_builder/pipeline_build_db.py`.
"""

import sqlite3
from pathlib import Path

import pytest

from src.constants import (
    DB_SCHEMA_VERSION_CURRENT,
    DB_SCHEMA_VERSION_LEGACY,
    DB_SCHEMA_VERSION_MIN_COMPATIBLE,
)
from src.utils import (
    IncompatibleDatabaseError,
    _check_schema_version,
    _read_schema_version,
)


def _make_db(tmp_path: Path, version: int) -> Path:
    """Create a tiny SQLite file stamped at `version`. Returns its path."""
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    return db


def test_constants_make_sense():
    """The compatibility range must be coherent."""
    assert DB_SCHEMA_VERSION_LEGACY == 0
    assert DB_SCHEMA_VERSION_MIN_COMPATIBLE >= 1
    assert DB_SCHEMA_VERSION_CURRENT >= DB_SCHEMA_VERSION_MIN_COMPATIBLE


def test_read_schema_version_returns_stamped_value(tmp_path):
    db = _make_db(tmp_path, 7)
    assert _read_schema_version(str(db)) == 7


def test_read_schema_version_zero_for_unstamped(tmp_path):
    """An unstamped DB returns 0 (SQLite default)."""
    db = tmp_path / "fresh.db"
    sqlite3.connect(db).close()  # creates an empty DB with no PRAGMA
    assert _read_schema_version(str(db)) == DB_SCHEMA_VERSION_LEGACY


def test_check_accepts_current(tmp_path):
    db = _make_db(tmp_path, DB_SCHEMA_VERSION_CURRENT)
    _check_schema_version(str(db))  # no exception


def test_check_accepts_legacy_zero_with_log(tmp_path, caplog):
    """An unstamped (legacy) DB must be accepted with an info log,
    not rejected — protects users with DBs built before the gate."""
    db = _make_db(tmp_path, DB_SCHEMA_VERSION_LEGACY)
    with caplog.at_level("INFO"):
        _check_schema_version(str(db))
    assert "legacy build" in caplog.text


def test_check_rejects_newer_than_current(tmp_path):
    db = _make_db(tmp_path, DB_SCHEMA_VERSION_CURRENT + 1)
    with pytest.raises(IncompatibleDatabaseError) as exc:
        _check_schema_version(str(db))
    assert exc.value.found == DB_SCHEMA_VERSION_CURRENT + 1
    assert "newer than this app supports" in str(exc.value)


def test_check_rejects_older_than_min(tmp_path):
    """A non-zero version below MIN_COMPATIBLE is a hard reject — the
    legacy-zero special case shouldn't extend to other small numbers."""
    if DB_SCHEMA_VERSION_MIN_COMPATIBLE <= 1:
        pytest.skip("nothing < MIN_COMPATIBLE to test here")
    db = _make_db(tmp_path, DB_SCHEMA_VERSION_MIN_COMPATIBLE - 1)
    with pytest.raises(IncompatibleDatabaseError):
        _check_schema_version(str(db))


def test_pipeline_stamping_writes_current_version(tmp_path):
    """The pipeline's _stamp_schema_version helper must write the
    constant the app reads — guards against drift between writer and
    reader of the same value."""
    from db_builder.pipeline_build_db import _stamp_schema_version

    db = tmp_path / "stamp.db"
    sqlite3.connect(db).close()  # empty DB; default user_version=0
    _stamp_schema_version(db)
    assert _read_schema_version(str(db)) == DB_SCHEMA_VERSION_CURRENT
