import csv
import io
import logging
import os
import shutil
import sqlite3
import urllib.request
from contextlib import closing

import streamlit as st

from src import database, db_version
from src.constants import (
    DB_SCHEMA_VERSION_CURRENT,
    DB_SCHEMA_VERSION_LEGACY,
    DB_SCHEMA_VERSION_MIN_COMPATIBLE,
)
from src.metrics import METRICS

_DOWNLOAD_TIMEOUT_SECONDS = 300
log = logging.getLogger("euka.utils")

# Placeholder tag recorded when we download the DB but couldn't learn the
# release tag (e.g. the download URL worked but the Releases API was briefly
# down). It sorts lexicographically *before* any real `db-YYYY...` tag, so the
# next successful check sees the real latest as strictly newer and self-heals.
# Crucially it marks the DB as app-managed (a sidecar exists), so it is not
# mistaken for a user-provided file and frozen.
_UNKNOWN_TAG = "db-0000.00.00.0000"


class IncompatibleDatabaseError(RuntimeError):
    """Raised when `eukaryotes.db` exists but is at an incompatible
    schema version. Carries the read version and the compatible range."""

    def __init__(self, found: int, min_compat: int, current: int):
        self.found = found
        self.min_compat = min_compat
        self.current = current
        if found > current:
            msg = (
                f"eukaryotes.db schema version {found} is newer than this app supports "
                f"(max {current}). Update the app or delete eukaryotes.db to re-download."
            )
        else:
            msg = (
                f"eukaryotes.db schema version {found} is older than the minimum "
                f"this app supports ({min_compat}). Delete eukaryotes.db to re-download "
                f"the latest release."
            )
        super().__init__(msg)


def _read_schema_version(db_path: str) -> int:
    """Return the `PRAGMA user_version` of `db_path`. Returns 0 on a
    legacy (pre-stamping) DB; SQLite's default for unstamped DBs is 0."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _check_schema_version(db_path: str) -> None:
    """Validate that `db_path` is at a schema version this app can serve.

    Treats `DB_SCHEMA_VERSION_LEGACY` (0) as equivalent to the current
    minimum-compatible version, so DBs built before the gate existed
    keep working without a forced rebuild.
    """
    found = _read_schema_version(db_path)
    if found == DB_SCHEMA_VERSION_LEGACY:
        log.info(
            "eukaryotes.db has no schema version stamp (legacy build) — "
            "treating as compatible with v%d.", DB_SCHEMA_VERSION_MIN_COMPATIBLE,
        )
        return
    if found < DB_SCHEMA_VERSION_MIN_COMPATIBLE or found > DB_SCHEMA_VERSION_CURRENT:
        raise IncompatibleDatabaseError(
            found, DB_SCHEMA_VERSION_MIN_COMPATIBLE, DB_SCHEMA_VERSION_CURRENT,
        )
    log.info("eukaryotes.db schema version %d — OK.", found)


def _read_version(version_path: str) -> str | None:
    """Return the release tag recorded for the on-disk DB, or None if the
    sidecar is absent/empty (a user-provided or pre-existing DB)."""
    try:
        with open(version_path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _write_version(version_path: str, tag: str | None) -> None:
    """Record which release the on-disk DB came from (best-effort)."""
    if not tag:
        return
    try:
        with open(version_path, "w", encoding="utf-8") as f:
            f.write(tag)
    except OSError as e:
        log.info("Could not write DB version sidecar %s: %s", version_path, e)


def _download_and_install(download_url: str, db_path: str) -> None:
    """Download the DB to a temp file, validate its schema, then atomically
    move it into place.

    Validating the temp file *before* the `os.replace` means a broken or
    schema-incompatible release can never clobber a working DB — the swap
    only happens once the new file is known good. Raises on network failure
    or an incompatible schema.
    """
    tmp_path = f"{db_path}.tmp"
    try:
        with urllib.request.urlopen(download_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response, \
             open(tmp_path, "wb") as out:
            shutil.copyfileobj(response, out)
        _check_schema_version(tmp_path)  # raises IncompatibleDatabaseError
        os.replace(tmp_path, db_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _download_or_fail(download_url: str, db_path: str, spinner_msg: str) -> None:
    """Download+install; on any failure surface st.error and raise
    RuntimeError (the hard-failure path when there's no usable DB)."""
    try:
        with st.spinner(spinner_msg):
            _download_and_install(download_url, db_path)
    except IncompatibleDatabaseError as e:
        st.error(str(e))
        raise RuntimeError("incompatible database downloaded") from e
    except Exception as e:
        st.error(f"Could not download database: {e}")
        raise RuntimeError("database download failed") from e


def _try_refresh(download_url: str, db_path: str, latest_tag: str) -> bool:
    """Attempt to swap in a newer release. Returns True on success; on any
    failure logs and returns False so the current (still-valid) DB keeps
    serving — `_download_and_install` never clobbers it on a bad download."""
    try:
        with st.spinner("Updating to the latest database..."):
            _download_and_install(download_url, db_path)
        return True
    except Exception as e:
        log.warning("DB refresh to %s failed; keeping current DB: %s", latest_tag, e)
        return False


def _gate_schema(db_path: str) -> None:
    """Refuse an incompatible on-disk DB, surfacing the reason via st.error."""
    try:
        _check_schema_version(db_path)
    except IncompatibleDatabaseError as e:
        st.error(str(e))
        raise


def ensure_latest_database(db_path: str, version_path: str, download_url: str) -> str | None:
    """Ensure the freshest compatible database is on disk; return its release
    tag (or None when the on-disk DB's version is unknown).

    Behaviour:
    - No DB present → download the latest release, record its tag.
    - DB present with a recorded tag → download+swap only if a strictly newer
      release exists; otherwise keep it.
    - DB present WITHOUT a recorded tag (a user-provided / pre-existing file,
      e.g. a local build) → adopt it as-is and never auto-replace it (and skip
      the network entirely).
    - GitHub unreachable → keep whatever DB is on disk; only a completely
      missing DB is a hard failure.

    Called on a timer via the `ttl` on `cache.get_db_ready`, so a long-running
    app picks up the weekly rebuild without a reboot. Raises RuntimeError on a
    hard failure (after st.error) — matching the old `ensure_database`
    contract so the caller's `except RuntimeError` still applies.
    """
    local_tag = _read_version(version_path)
    have_db = os.path.exists(db_path)

    # Unmanaged/user-provided DB: adopt as-is, no network, never replace.
    if have_db and local_tag is None:
        _gate_schema(db_path)
        return None

    latest = db_version.fetch_latest_release()
    latest_tag = latest["tag"] if latest else None

    if not have_db:
        _download_or_fail(download_url, db_path, "Downloading database (this happens once)...")
        # Always record a sidecar so the DB is treated as app-managed on the
        # next check, even if the tag was momentarily unknowable.
        _write_version(version_path, latest_tag or _UNKNOWN_TAG)
        result_tag = latest_tag
    elif latest_tag and latest_tag > local_tag and _try_refresh(download_url, db_path, latest_tag):
        _write_version(version_path, latest_tag)
        result_tag = latest_tag
    else:
        result_tag = local_tag  # up to date, or refresh failed/unavailable

    _gate_schema(db_path)
    return result_tag

@st.cache_data(show_spinner="Preparing data for download...")
def generate_tsv(_conn, root_taxid, target_rank, _fetch_func):
    """
    Generate a TSV string for the given query limit dynamically.
    """
    
    # We resolve the actual taxa inside the cached function to avoid hashing huge lists
    query_taxa = _fetch_func(_conn, root_taxid, target_rank)

    if not query_taxa:
        return ""
    
    query_taxids = [t[0] for t in query_taxa]
    taxa_names = {t[0]: t[1] for t in query_taxa}
    
    metadata = database.build_phylum_metadata(_conn, query_taxids, exclude_empty=False)

    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')

    # Single source of truth for the TSV column schema: each entry is
    # (column_name, value_fn). Header row is `[name for name, _ in cols]`
    # and each data row is `[fn(tid, stats) for _, fn in cols]` — so the
    # header cannot drift from the row. Fixed prefix, then per-metric
    # species-covered count, then per-metric total-runs count, all in
    # METRICS order. `stats` is a CladeMetadata; dynamic field access via
    # getattr keeps the lambdas indexed by the m.coverage_key/m.total_key
    # strings stored on each Metric.
    columns: list[tuple[str, callable]] = [
        ("taxon_id", lambda tid, stats: tid),
        ("name", lambda tid, stats: taxa_names.get(tid, "Unknown")),
        ("total_species", lambda tid, stats: stats.n_rows),
    ]
    for m in METRICS:
        columns.append((m.tsv_count_column, lambda tid, stats, k=m.coverage_key: getattr(stats, k)))
    for m in METRICS:
        columns.append((m.tsv_total_column, lambda tid, stats, k=m.total_key: getattr(stats, k)))

    writer.writerow([name for name, _ in columns])
    for taxid in query_taxids:
        stats = metadata[taxid]
        writer.writerow([fn(taxid, stats) for _, fn in columns])

    return output.getvalue()
