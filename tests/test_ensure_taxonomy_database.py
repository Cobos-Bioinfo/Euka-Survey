"""Tests for `src.utils.ensure_taxonomy_database`, which pre-seeds ETE3's
NCBI taxonomy DB from the weekly release so `NCBITaxa()` never builds it
in-process (a ~3 GB RSS build that OOMs the Streamlit Cloud container).

The HTTP source is faked with a real tar.gz on disk, so the streaming
extract -> validate -> install path runs for real.
"""

import os
import sqlite3
import tarfile

import pytest

from src import utils


def _make_taxa_sqlite(path: str, taxid: int = 2759) -> None:
    """Minimal stand-in for an ETE3 taxa.sqlite: just the `species` row the
    validator looks for."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE species (taxid INT PRIMARY KEY, spname TEXT)")
    conn.execute("INSERT INTO species VALUES (?, 'Eukaryota')", (taxid,))
    conn.commit()
    conn.close()


def _make_archive(tmp_path, *, with_traverse=True, taxid=2759) -> str:
    """Build a taxa.tar.gz laid out like the workflow's `tar -C ~/.etetoolkit`."""
    src = tmp_path / "src"
    src.mkdir()
    _make_taxa_sqlite(str(src / "taxa.sqlite"), taxid)
    members = ["taxa.sqlite"]
    if with_traverse:
        (src / "taxa.sqlite.traverse.pkl").write_bytes(b"traverse")
        members.append("taxa.sqlite.traverse.pkl")
    archive = str(tmp_path / "taxa.tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for name in members:
            tar.add(str(src / name), arcname=name)
    return archive


@pytest.fixture
def dbfile(tmp_path):
    # Mirrors ETE3's default ~/.etetoolkit/taxa.sqlite, including a parent
    # directory that does not exist yet on a fresh container.
    return str(tmp_path / "home" / ".etetoolkit" / "taxa.sqlite")


def _serve(monkeypatch, archive_path):
    def fake_urlopen(url, timeout=None):
        return open(archive_path, "rb")
    monkeypatch.setattr(utils.urllib.request, "urlopen", fake_urlopen)


def _leftover_tmp_files(dbfile):
    folder = os.path.dirname(dbfile)
    if not os.path.isdir(folder):
        return []
    return [f for f in os.listdir(folder) if f.endswith(".tmp")]


def test_missing_taxonomy_is_downloaded_and_installed(dbfile, tmp_path, monkeypatch):
    _serve(monkeypatch, _make_archive(tmp_path))

    utils.ensure_taxonomy_database(dbfile, "http://example/taxa.tar.gz")

    assert os.path.exists(dbfile)
    assert open(dbfile + ".traverse.pkl", "rb").read() == b"traverse"
    utils._check_taxonomy(dbfile)  # installed DB is the validated one
    assert _leftover_tmp_files(dbfile) == []


def test_existing_taxonomy_is_kept_without_network(dbfile, monkeypatch):
    os.makedirs(os.path.dirname(dbfile))
    _make_taxa_sqlite(dbfile, taxid=1)  # e.g. a developer's own build
    open(dbfile + ".traverse.pkl", "wb").close()

    def _boom(*a, **k):
        raise AssertionError("must not hit the network when the taxonomy exists")
    monkeypatch.setattr(utils.urllib.request, "urlopen", _boom)

    utils.ensure_taxonomy_database(dbfile, "http://example/taxa.tar.gz")

    conn = sqlite3.connect(dbfile)
    assert conn.execute("SELECT taxid FROM species").fetchone()[0] == 1  # untouched
    conn.close()


def test_archive_missing_traverse_installs_nothing(dbfile, tmp_path, monkeypatch):
    _serve(monkeypatch, _make_archive(tmp_path, with_traverse=False))

    utils.ensure_taxonomy_database(dbfile, "http://example/taxa.tar.gz")  # must not raise

    # Nothing half-installed: NCBITaxa() will fall back to its own build.
    assert not os.path.exists(dbfile)
    assert not os.path.exists(dbfile + ".traverse.pkl")
    assert _leftover_tmp_files(dbfile) == []


def test_invalid_taxonomy_db_installs_nothing(dbfile, tmp_path, monkeypatch):
    _serve(monkeypatch, _make_archive(tmp_path, taxid=1))  # no Eukaryota row

    utils.ensure_taxonomy_database(dbfile, "http://example/taxa.tar.gz")

    assert not os.path.exists(dbfile)
    assert not os.path.exists(dbfile + ".traverse.pkl")
    assert _leftover_tmp_files(dbfile) == []


def test_download_failure_is_not_fatal(dbfile, monkeypatch):
    def _offline(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(utils.urllib.request, "urlopen", _offline)

    utils.ensure_taxonomy_database(dbfile, "http://example/taxa.tar.gz")  # must not raise

    assert not os.path.exists(dbfile)
