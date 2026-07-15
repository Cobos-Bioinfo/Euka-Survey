#!/usr/bin/env python3
"""
pipeline_build_db.py — Build a SQLite database of taxIDs with assemblies, annotations, and reads.

Writes to `eukaryote_taxid_features_YYYY_MM_DD.db.partial` while in progress;
atomically renames to `eukaryote_taxid_features_YYYY_MM_DD.db` only on full
success. On any step failure, the `.partial` file is left on disk for
inspection and the workflow's `mv eukaryote_taxid_features_*.db` glob will
not pick it up.

Resumability: each fetch step (1-4) pickles its result into a per-build
snapshot directory (`.<partial-name>.snapshots/`). On retry, a cached
snapshot is loaded instead of re-fetching — so an ENA hiccup at step 4
no longer forces a fresh ~30-minute network round-trip. Snapshots are
deleted on successful completion. Use `--from-step N` to force a re-run
from step N (purges snapshots with step number ≥ N).

Steps:
  [1/7] Local ETE3 SQLite     → all descendant species of Eukaryota
  [2/7] NCBI datasets CLI     → assemblies per taxid
  [3/7] Annotrieve API        → annotations per taxid
  [4/7] ENA portal API        → long-/short-read RNA-Seq runs per taxid
  [5/7] sqlite3               → taxid_features table
  [6/7] ete3 lineages         → precomputed_clade_features table
  [7/7] ete3 + sqlite3        → precomputed_taxa table (common clades)
"""

import argparse
import datetime
import logging
import os
import pickle
import re
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

from src.constants import DB_SCHEMA_VERSION_CURRENT, EUKARYOTE_TXID
from src.ete_utils import get_all_descendant_taxids
from db_builder.build_db.get_assemblies import get_assemblies
from db_builder.build_db.get_annotations import fetch_annotrieve_annotations
from db_builder.build_db.get_reads import fetch_ena_reads
from db_builder.build_db.build_database import build_database


TOTAL_STEPS = 7
log = logging.getLogger("euka.pipeline")

T = TypeVar("T")


class PipelineError(RuntimeError):
    """A pipeline step failed. The exception's `__cause__` carries the
    original failure."""


def _step(num: int, label: str):
    """Decorator-ish helper: log the step header and turn any exception
    into a PipelineError tagged with the step number, so the top-level
    handler can produce a clean error summary."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            log.info("[%d/%d] %s", num, TOTAL_STEPS, label)
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                raise PipelineError(f"step {num}/{TOTAL_STEPS} ({label}) failed: {e}") from e
        return wrapped
    return decorator


# ── Per-step snapshots (resumability) ────────────────────────────────
#
# Fetch steps 1-4 are the expensive ones (network / external CLI). They
# pickle their return value into `<snap_dir>/stepN_<key>.pkl` keyed off
# the in-progress .partial path, so a retry after a step-5+ crash skips
# straight to step 5 without re-fetching.
#
# Steps 5-7 don't snapshot — they write directly into the .partial DB,
# which IS the snapshot for downstream steps. On retry the .partial is
# discarded (it may be mid-write) and steps 5-7 run from the cached
# fetches; that's cheap relative to the network steps.
#
# The snapshot directory is a sibling of the .partial file with a
# leading dot, so `mv eukaryote_taxid_features_*.db` and other globs
# that target the dated DB don't pick it up.

_SNAPSHOT_STEP_RE = re.compile(r"step(\d+)_")


def _snapshot_dir(partial_path: Path) -> Path:
    """Return the snapshot directory paired with this build's .partial."""
    return partial_path.parent / f".{partial_path.name}.snapshots"


def _snapshot_path(snap_dir: Path, step_num: int, key: str) -> Path:
    return snap_dir / f"step{step_num}_{key}.pkl"


def _save_snapshot(snap_dir: Path, step_num: int, key: str, data) -> None:
    """Pickle `data` to a tmp file, then `os.replace` into place — so a
    process kill mid-write can't leave a half-written snapshot."""
    snap_dir.mkdir(parents=True, exist_ok=True)
    final = _snapshot_path(snap_dir, step_num, key)
    tmp = final.with_suffix(final.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, final)
    log.info("  Snapshot saved: %s", final.name)


def _load_snapshot(snap_dir: Path, step_num: int, key: str):
    """Return cached data for (step_num, key), or None if absent."""
    path = _snapshot_path(snap_dir, step_num, key)
    if not path.exists():
        return None
    with path.open("rb") as f:
        return pickle.load(f)


def _run_cached(
    snap_dir: Path, step_num: int, key: str, fn: Callable[[], T],
) -> T:
    """Run `fn` unless a snapshot for (step_num, key) already exists.

    Cache miss → run, persist the result, return it.
    Cache hit  → log the resume and return the cached value (the
                 step's normal logging is skipped so the user sees
                 "Resumed" rather than a false "Fetching..." header).
    """
    cached = _load_snapshot(snap_dir, step_num, key)
    if cached is not None:
        log.info("[%d/%d] Resumed from snapshot: %s",
                 step_num, TOTAL_STEPS, _snapshot_path(snap_dir, step_num, key).name)
        return cached
    result = fn()
    _save_snapshot(snap_dir, step_num, key, result)
    return result


def _purge_snapshots_from(snap_dir: Path, from_step: int) -> int:
    """Delete snapshots for steps ≥ `from_step`. Returns the count purged.

    `--from-step N` calls this before the run, so a user who knows the
    upstream data is stale (e.g. ENA result was empty) can force a
    re-fetch from step N onward while keeping any earlier cached steps.
    """
    if not snap_dir.exists():
        return 0
    purged = 0
    for pkl in snap_dir.glob("step*_*.pkl"):
        match = _SNAPSHOT_STEP_RE.match(pkl.name)
        if match and int(match.group(1)) >= from_step:
            pkl.unlink()
            log.info("Purged snapshot: %s", pkl.name)
            purged += 1
    return purged


def _cleanup_snapshots(snap_dir: Path) -> None:
    """Remove the snapshot dir after a successful build."""
    if not snap_dir.exists():
        return
    for pkl in snap_dir.glob("step*_*.pkl"):
        pkl.unlink()
    # Empty the dir before rmdir — leave any user-dropped files alone.
    try:
        snap_dir.rmdir()
    except OSError:
        log.debug("Snapshot dir %s not empty; leaving non-snapshot files in place.", snap_dir)


@_step(1, "Fetching all descendant species of Eukaryota")
def step_descendants():
    taxids = get_all_descendant_taxids(EUKARYOTE_TXID)
    log.info("  Found %d descendant species of Eukaryota (taxID %d)", len(taxids), EUKARYOTE_TXID)
    return taxids


@_step(2, "Fetching assemblies (NCBI datasets CLI)")
def step_assemblies():
    a = get_assemblies(EUKARYOTE_TXID)
    log.info("  Found assemblies for %d unique taxa", len(a))
    return a


@_step(3, "Fetching annotations (Annotrieve)")
def step_annotations():
    a = fetch_annotrieve_annotations()
    log.info("  Found annotations for %d taxa", len(a))
    return a


@_step(4, "Fetching RNA-Seq runs (ENA)")
def step_reads():
    long_reads, short_reads, count = fetch_ena_reads()
    log.info("  Fetched %d runs (%d long-read taxa, %d short-read taxa)",
             count, len(long_reads), len(short_reads))
    # Sanity check: humans/mice dominate transcriptomic ENA runs.
    if 9606 not in short_reads and 10090 not in short_reads:
        log.warning(
            "Neither humans (9606) nor mice (10090) found in short-read taxa — "
            "ENA response may have been truncated or the query may need review."
        )
    return long_reads, short_reads, count


@_step(5, "Writing taxid_features table")
def step_build_db(partial_path, all_taxids, assemblies, annotations, short_reads, long_reads):
    log.info("  Output: %s", partial_path.name)
    return build_database(
        all_taxids=all_taxids,
        assembly_taxids=assemblies,
        annotation_taxids=annotations,
        short_read_taxids=short_reads,
        long_read_taxids=long_reads,
        db_path=partial_path,
    )


@_step(6, "Precomputing clade aggregations")
def step_precompute_clades(partial_path):
    # Imported here so a missing optional dep doesn't crash earlier steps.
    from db_builder.precompute_aggregations import precompute_clades
    precompute_clades(partial_path)


@_step(7, "Baking common-clade UI shortcuts (precompute_taxa)")
def step_precompute_taxa(partial_path):
    from db_builder.precompute_taxa import precompute_common_clades
    precompute_common_clades(partial_path)


def _stamp_schema_version(path: Path) -> None:
    """Set PRAGMA user_version on the produced DB.

    The app reads this on startup to refuse incompatible DBs (see
    src/utils.py::ensure_latest_database). Stamped after the final atomic
    rename so an interrupted build never produces a versioned-looking
    .partial file.
    """
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(path)) as conn:
        # SQLite's PRAGMA does not accept parametrized values.
        conn.execute(f"PRAGMA user_version = {int(DB_SCHEMA_VERSION_CURRENT)}")
        conn.commit()
    log.info("Stamped %s with schema version %d", path.name, DB_SCHEMA_VERSION_CURRENT)


def _parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the EukaSurvey precomputed SQLite database.",
    )
    parser.add_argument(
        "--from-step", type=int, default=None, metavar="N",
        help=(
            "Force re-running from step N (1-7). Snapshots for steps "
            "< N are kept; snapshots for steps ≥ N are purged before "
            "the run. Useful when you know upstream fetch data is stale."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if args.from_step is not None and not (1 <= args.from_step <= TOTAL_STEPS):
        log.error("--from-step must be in 1..%d, got %d", TOTAL_STEPS, args.from_step)
        return 2

    log.info("--- Starting Eukaryote Feature Pipeline ---")
    start_time = time.time()

    today_str = datetime.date.today().strftime("%Y_%m_%d")
    final_path = Path(f"eukaryote_taxid_features_{today_str}.db")
    partial_path = final_path.with_suffix(".db.partial")
    snap_dir = _snapshot_dir(partial_path)

    # The .partial may be mid-write from a prior crash — always start
    # fresh. Cached fetch snapshots (in `snap_dir`) survive so steps 1-4
    # can resume without re-hitting the network.
    if partial_path.exists():
        log.info("Removing stale partial DB: %s", partial_path)
        partial_path.unlink()

    if args.from_step is not None:
        purged = _purge_snapshots_from(snap_dir, args.from_step)
        log.info("--from-step %d: purged %d snapshot(s) ≥ step %d.",
                 args.from_step, purged, args.from_step)

    if snap_dir.exists():
        cached_pkls = sorted(snap_dir.glob("step*_*.pkl"))
        if cached_pkls:
            log.info("Resuming with %d cached snapshot(s) from a prior run: %s",
                     len(cached_pkls), [p.name for p in cached_pkls])

    try:
        all_taxids  = _run_cached(snap_dir, 1, "descendants", step_descendants)
        assemblies  = _run_cached(snap_dir, 2, "assemblies",  step_assemblies)
        annotations = _run_cached(snap_dir, 3, "annotations", step_annotations)
        long_reads, short_reads, _ = _run_cached(snap_dir, 4, "reads", step_reads)
        rows_written = step_build_db(
            partial_path, all_taxids, assemblies, annotations, short_reads, long_reads,
        )
        step_precompute_clades(partial_path)
        step_precompute_taxa(partial_path)

        # Atomic rename — only after every step has succeeded.
        os.replace(partial_path, final_path)

        # Stamp the schema version AFTER the atomic rename so an
        # interrupted build cannot leave a versioned-looking .partial.
        _stamp_schema_version(final_path)

        # Build succeeded end-to-end — snapshots are no longer needed.
        _cleanup_snapshots(snap_dir)

        elapsed = time.time() - start_time
        log.info("Pipeline completed successfully in %.2f seconds.", elapsed)
        log.info("Wrote %d records to %s.", rows_written, final_path.name)
        return 0

    except PipelineError as e:
        log.error("PIPELINE FAILED: %s", e)
        if partial_path.exists():
            log.error("Partial output left at %s for inspection.", partial_path)
        if snap_dir.exists() and any(snap_dir.glob("step*_*.pkl")):
            log.info(
                "Snapshots kept at %s — re-run the pipeline to resume "
                "from the last successful step.", snap_dir,
            )
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sys.exit(main())
