# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EukaSurvey is a Streamlit web app for exploring genomic sequencing data availability (whole-genome
assemblies, functional annotations, short- and long-read RNA-Seq) across the eukaryotic tree of
life, backed by a precomputed SQLite database (`eukaryotes.db`).

## Running the app

Dependencies are managed with [uv](https://docs.astral.sh/uv/) via `pyproject.toml` +
`uv.lock`. Conda and `environment.yml` are gone; `packages.txt` remains only as the Streamlit
Cloud apt manifest (the five Qt5 runtime libs ete3/PyQt5 need headless).

```bash
uv sync                         # web-app deps from uv.lock
uv run streamlit run app.py
```

For the offline DB-build pipeline use `uv sync --extra pipeline` (adds `tenacity`). For tests
use `uv sync --group dev` (adds `pytest`). The `ncbi-datasets-cli` is a standalone NCBI binary
and is not a Python dep — see `docs/PIPELINE.md`.

If `eukaryotes.db` is missing locally, `app.py` (via `src/utils.ensure_latest_database`) downloads
the precomputed copy from the latest GitHub Release on first run and validates its `PRAGMA
user_version` against the app's compatibility range (see "Schema versioning" below). The same
function also re-checks GitHub roughly hourly (the `ttl` on `cache.get_db_ready`) and hot-swaps in a
newer weekly build without a reboot — see "Database refresh / weekly updates" below.

There is a pytest suite under `tests/` (run with `uv run pytest`). The only other CI is the
weekly DB-build workflow (`.github/workflows/update_db.yml`).

## Architecture

### Two halves of the project

1. **`app.py` + `ui/` + `src/`** — the Streamlit app. `app.py` is a thin controller that wires the
   `ui/` view sections (one `render_*` each, cross-section state via `ui/state.py`); `src/` holds
   the domain logic + `@st.cache_*` wrappers. Reads the prebuilt, read-only `eukaryotes.db`.
2. **`db_builder/`** — an offline pipeline that fetches data from NCBI/Annotrieve/ENA and produces
   `eukaryotes.db`. Run manually or via the weekly GitHub Action; not invoked by the web app.

Both are first-class importable Python packages declared in `pyproject.toml`'s
`tool.hatch.build.targets.wheel.packages`, so no `sys.path` hacks are needed.

### Database (`eukaryotes.db`) — three tables

- `taxid_features`: one row per species-level taxid with raw counts
  (`assembly_count`, `annotation_count`, `short_read_count`, `long_read_count`).
- `precomputed_clade_features`: one row **per taxid at any rank** (not just leaves) with rolled-up
  aggregates across its entire subtree — `n_rows` (species count), `c_ass/c_ann/c_rna/c_lng`
  (species *covered*, i.e. has ≥1 of that resource) and `s_ass/s_ann/s_rna/s_lng` (total resource
  *counts*). This is the table the app actually queries for stats — `src/database.py` reads it
  directly with no on-the-fly rollups.
- `precomputed_taxa`: maps `(root_taxid, target_rank) -> [(taxid, name), ...]` for the six "common"
  root clades (Eukaryota, Animals, Mammalia, Primates, Fungi, Plants) × six ranks
  (phylum/class/order/family/genus/species), so the UI can skip live ETE3 lookups for common
  queries. For any other root/rank combination, the app falls back to `src/taxonomy.get_taxa_at_rank`
  (live ETE3 traversal).

### Schema versioning (`PRAGMA user_version`)

`src/constants.py` declares the compatibility window:
`DB_SCHEMA_VERSION_CURRENT`, `DB_SCHEMA_VERSION_MIN_COMPATIBLE`, `DB_SCHEMA_VERSION_LEGACY=0`.

- The pipeline's `_stamp_schema_version` writes `DB_SCHEMA_VERSION_CURRENT` into the produced DB
  **after** the atomic `.partial` → `.db` rename.
- The app's `src/utils._check_schema_version` reads it on startup and raises
  `IncompatibleDatabaseError` for DBs newer than current or older than min-compatible. Legacy
  unstamped DBs (`user_version=0`) are accepted with an info log to avoid forcing existing users
  to redownload.
- If you change the schema, bump `DB_SCHEMA_VERSION_CURRENT` in `src/constants.py` — the test
  `test_schema_version.py::test_pipeline_stamping_writes_current_version` guards against writer
  ↔ reader drift.

### `src/` modules

- `database.py` — pure SQL layer over `precomputed_clade_features` / `precomputed_taxa`.
  `build_phylum_metadata` bulk-fetches per-taxid stats (chunked to respect SQLite's 999-variable
  limit). `get_filtered_taxa_metadata` pushes filtering/sorting/limiting entirely into SQL for
  precomputed root/rank combos. Shared helpers `_row_to_metadata`,
  `filter_sort_limit_metadata`, and the `FilterLogic` enum keep the SQL and Python-fallback
  paths semantically identical.
- `taxonomy.py` — `get_taxa_at_rank` via live ETE3 (`NCBITaxa`) descendant traversal, used as
  the fallback when a root/rank pair isn't in `precomputed_taxa`. `resolve_valid_ranks` (rank
  dropdown) and `get_lineage_breadcrumb` (sidebar breadcrumb) are `@lru_cache`d; unknown taxids
  raise `UnknownTaxonError`.
- `ete_utils.py` — `get_ncbi()` (the `threading.local()`-cached `NCBITaxa` accessor every prod
  call site uses) plus taxid <-> name/rank lookups via ETE3 and `get_all_descendant_taxids`,
  which queries ETE3's underlying SQLite taxonomy DB directly with a recursive CTE (used by the
  offline pipeline, not the app).
- `metrics.py` — single source of truth for the four resources: the `Metric` config table (bar
  colors, filter/sort/card/TSV/external-link config) + the frozen `CladeMetadata` dataclass. Edit
  `METRICS` and every consumer (`database`, `visualization`, `ui/`, `utils`) follows.
- `cache.py` — **all** `@st.cache_*` wrappers: `get_db_ready`/`get_db_connection`
  (`@st.cache_resource`) + the query/render `@st.cache_data` caches. Imported by `app.py` + `ui/`.
- `visualization.py` — builds the ETE3 phylogenetic tree SVG and hosts `render_tree_in_process`
  (the spawn-subprocess entrypoint). Pins `matplotlib.use("Agg")` at import time. Per-leaf
  divergent bar charts (assemblies/annotations on the left, RNA-Seq/long-read on the right) are
  pre-rendered as PNGs into a per-render `tempfile.TemporaryDirectory` and embedded via `ImgFace`
  — there is no shared `.tmp_bars/`. Lineage lookups are batched via `get_lineage_translator`.
- `wikipedia.py` — `get_taxon_summary(name)`: cached (24h) Wikipedia REST-summary fetch for the
  root-taxon "About" card in `ui/summary.py`; follows redirects, fails silent → `None`.
- `db_version.py` — GitHub Release metadata. `fetch_latest_release()` (uncached; called behind
  `get_db_ready`'s ttl) powers the weekly DB self-update; `date_from_tag()` / `release_url()` turn the
  served DB's tag into the "Database built …" footer in `ui/sidebar.py`. Fails silent → `None`.
- `utils.py` — `ensure_latest_database` (downloads `eukaryotes.db` if absent, hot-swaps a newer
  weekly release, validates schema version),
  `generate_tsv` (exports query results as TSV), and the schema-version helpers
  (`_read_schema_version`, `_check_schema_version`, `IncompatibleDatabaseError`).
- `constants.py` — schema-version constants and other module-level shared values.

### `ui/` modules

`app.py` calls one `render_*` per page section; sections never call each other — cross-section
state flows through `ui/state.py`'s frozen dataclasses: **`RootChoice`** (sidebar, "which clade?")
→ **`QueryState`** (Explore Results, which owns the breakdown rank). `query_config.py` (sidebar
root picker), `sidebar.py` (Help & Resources), `summary.py` (resource cards + Wikipedia `About`
card), `tree.py` (Explore Results: segmented rank control + form → 🌳 Tree / 📊 Table tabs),
`export.py` (full-breakdown TSV + preview).

### Why tree rendering happens in a subprocess

ETE3 needs PyQt5's `QApplication` created on a process's main thread, but Streamlit runs callbacks
on worker threads. `src/cache.py`'s `generate_tree_svg_cached` spawns a fresh process
(`multiprocessing.get_context('spawn')`) running `visualization.render_tree_in_process`, which
writes an SVG to a temp file that the parent reads back. The subprocess uses Qt's `offscreen` platform
(`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`) — there is no Xvfb / pyvirtualdisplay
dependency anywhere. The rendered SVG can't be passed to `st.image` directly (PIL chokes on raw
SVG bytes), so it's written to a temp `.svg` file and read back by path.

### Streamlit caching layers (`src/cache.py`)

- `get_db_ready`: `@st.cache_resource(ttl=DB_REFRESH_TTL_SECONDS)`. Ensures the DB is present,
  compatible, and up to date, returning its release tag. The `ttl` (hourly) is what lets a
  long-running app pick up the weekly rebuild without a reboot.
- `get_db_connection(db_tag)`: `@st.cache_resource(max_entries=2)`, read-only connection
  (`mode=ro`, `check_same_thread=False`). Keyed on the tag from `get_db_ready`, so a swapped-in
  release yields a fresh connection to the new file. `db_tag` must stay un-`_`-prefixed (else
  Streamlit drops it from the cache key).
- `get_taxa_count_cached`, `fetch_taxa_cached`, `get_phylum_metadata_cached`,
  `get_filtered_taxa_metadata_cached`, `generate_tree_svg_cached`: `@st.cache_data` wrappers around
  the `src/` functions, keyed on query params (taxids passed as tuples since they must be hashable).
- `utils.generate_tsv` and `wikipedia.get_taxon_summary` carry their own `@st.cache_data` in their
  own modules. `db_version.fetch_latest_release` is deliberately uncached (its caller already runs
  behind `get_db_ready`'s ttl).

### Database refresh / weekly updates

The DB is rebuilt weekly (Sunday 03:20 UTC) and published as a new date-tagged GitHub Release. A
Streamlit `cache_resource` value normally lives for the whole server process, and Community Cloud's
filesystem is ephemeral, so an app that's kept awake (via the `streamlit-keepalive` bot) would never
re-download and would serve stale data indefinitely. The fix is entirely in-app, no reboot required:

- `get_db_ready` has a `ttl` (`DB_REFRESH_TTL_SECONDS`, hourly). On each expiry it re-runs
  `utils.ensure_latest_database`, which asks GitHub for the latest release and, if it's newer than a
  small sidecar version file (`eukaryotes.db.version`, gitignored), downloads it to a temp file,
  validates the schema **before** the atomic `os.replace` (a bad release can't clobber a good DB),
  and records the new tag.
- `get_db_ready` returns the on-disk tag; `get_db_connection(db_tag)` is keyed on it, so a new tag is
  a cache miss that opens a fresh read-only connection to the swapped file — no `.clear()` / reboot.
- Safety rules in `ensure_latest_database`: a pre-existing DB with **no** sidecar (e.g. a local build
  used for the thesis) is adopted as-is and never auto-replaced (its tag reports as `None` → sidebar
  shows "local build"); a GitHub outage keeps the current DB serving; only a completely missing DB is
  a hard failure. Covered by `tests/test_ensure_latest_database.py`.
- The `streamlit-keepalive` repo (separate) has an extra `0 5 * * 0` cron so a real page visit ~1h
  after the build triggers the freshness check promptly instead of waiting for the next 6-hourly ping.

### Query flow (root taxon -> rank -> tree/TSV)

1. User picks a root taxid in the **sidebar** (`ui/query_config.py`; common clade or arbitrary NCBI
   taxid), then a breakdown rank in **Explore Results** (`ui/tree.py`). Valid ranks are restricted
   to those *below* the root's own rank (computed live via ETE3 lineage lookup).
2. `get_taxa_count_cached` checks `precomputed_taxa` first (`is_precomputed = True` if rows exist).
   If empty, falls back to `fetch_taxa_cached` -> `taxonomy.get_taxa_at_rank` (live ETE3).
3. On "Generate Tree & Table":
   - If precomputed, `get_filtered_taxa_metadata_cached` does filtering/sorting/limiting in SQL.
   - Otherwise, `get_phylum_metadata_cached` fetches all metadata and `filter_sort_limit_metadata`
     applies the same logic in Python. Both paths share `_row_to_metadata` and `FilterLogic`
     so they cannot drift — the parity matrix in `tests/test_filters_parity.py` exercises 16
     scenarios across them.
   - The resulting metadata feeds two synced `st.tabs` views: the 🌳 Tree (SVG) and the 📊 Table
     (`st.dataframe`), each with its own download.
4. TSV export (`utils.generate_tsv`) always re-resolves the full taxa list and calls
   `build_phylum_metadata` directly (not the filtered/sorted/limited path).

## `db_builder/` pipeline

`pipeline_build_db.py` orchestrates 7 steps (each wrapped in a `@_step(n, label)` decorator that
converts any exception into a `PipelineError` tagged with the step number):

1. `src.ete_utils.get_all_descendant_taxids(2759)` — every descendant taxid of Eukaryota via
   ETE3's local SQLite.
2. `build_db/get_assemblies.py` — shells out to the NCBI `datasets summary genome taxon` CLI.
3. `build_db/get_annotations.py` — queries the Annotrieve frequencies API.
4. `build_db/get_reads.py` — queries the ENA portal API for RNA-Seq runs, splitting by
   `instrument_platform` into long-read (OXFORD_NANOPORE/PACBIO_SMRT) vs short-read. **Uses
   `format=json` + `r.json()`** — the TSV+`iter_lines` variant caused silent ~28 % data loss
   (see `REFACTORING_CHANGELOG.md`).
5. `build_db/build_database.py` — writes the merged counts into `taxid_features`.
6. `precompute_aggregations.py` — rolls up `taxid_features` (filtered to species-rank rows)
   through ETE3 lineages into `precomputed_clade_features`. Missing-lineage species are
   **skipped**, not silently treated as `[taxid]` (that prior bug under-counted ancestors —
   guarded by `tests/test_aggregations.py`).
7. `precompute_taxa.py` — populates `precomputed_taxa` for the six common root clades.

Output is written atomically: `eukaryote_taxid_features_YYYY_MM_DD.db.partial` →
`os.replace` rename on success, then `_stamp_schema_version` writes `PRAGMA user_version`.

Steps 1–4 (the network/CLI fetches) pickle their return values into a sibling snapshot
directory `.eukaryote_taxid_features_YYYY_MM_DD.db.partial.snapshots/`. On retry, cached
snapshots are loaded instead of re-fetching; on successful completion they're deleted. Steps
5–7 don't snapshot (the `.partial` DB is the state). Use `--from-step N` to purge snapshots
≥ N before a run when upstream data is stale. Helpers + behavior covered by
`tests/test_pipeline_snapshots.py`.

The weekly GitHub Action (`.github/workflows/update_db.yml`) runs the whole pipeline under
`astral-sh/setup-uv@v6`, renames the dated output to `eukaryotes.db`, runs a size + row-count
smoke test, and publishes it as a date-tagged GitHub Release
(`db-YYYY.MM.DD.HHMM`, with `make_latest: true`). The app's `/releases/latest/download/eukaryotes.db`
URL keeps resolving to the most recent build; older releases stay around for rollback.

## Tests

Under `tests/`, run with `uv run pytest`. Key fixtures and files:

- `conftest.py::fixture_db` — synthetic 6-taxa in-memory SQLite for fast, deterministic tests.
- `test_filters_parity.py` — SQL vs Python parity matrix (16 scenarios) over the unified filter
  helpers. This is the regression net for any change to filter / sort / limit behavior.
- `test_aggregations.py` — guards the precompute_aggregations missing-lineage skip; uses
  monkeypatched `NCBITaxa.get_rank` + `get_lineage_translator` to construct the narrow
  species-no-lineage case that the original bug fired in.
- `test_schema_version.py` — round-trip between the pipeline's stamper and the app's reader,
  including the legacy-zero allowance.

## Gotchas

- `eukaryotes.db` is gitignored (`*.db`) — don't expect it to be present in a fresh checkout;
  either let the app download it or run the `db_builder` pipeline. Any `WORKS_*.db` backup files
  are also covered by `*.db`.
- The web app's read-only connection means any schema/table the app queries (`precomputed_*`)
  must already exist in `eukaryotes.db`; `src/database.py` guards with `try/except
  sqlite3.OperationalError` for tables that may not exist yet.
- When changing filter/sort options in `app.py`, both the SQL path (`get_filtered_taxa_metadata`
  in `src/database.py`) and the Python fallback path (`filter_sort_limit_metadata` in the same
  module) read from shared helpers and must stay aligned — bumping the parity matrix in
  `tests/test_filters_parity.py` is the cheapest way to catch drift.
- When changing the DB schema, bump `DB_SCHEMA_VERSION_CURRENT` in `src/constants.py` and update
  `DB_SCHEMA_VERSION_MIN_COMPATIBLE` if the change is breaking. Pipeline ↔ app stamp/read drift
  is caught by `test_schema_version.py`.
- ENA fetching (`get_reads.py`) must stay on `format=json` + `r.json()`. The "stream TSV with
  `iter_lines`" optimization looked safe but silently truncated results to ~72 % of the true
  count; the cause is undiagnosed (likely a server-side TSV cap) and the optimization is parked.
- `packages.txt` apt names must use Debian **trixie** `t64` suffixes — Streamlit Cloud builds on
  trixie, where the 64-bit `time_t` transition renamed libs (e.g. glib is `libglib2.0-0t64`, NOT
  `libglib2.0-0`; the bare name is unsatisfiable and makes `apt-get` abort the *whole* file). A
  missing Qt/glib lib shows up as `ImportError: lib*.so.N: cannot open shared object file` from
  `from PyQt5 import QtGui` (via `src/visualization.py`), plus a *misleading* cascade
  `cannot import name 'get_db_connection' from 'src.cache'` — the latter is not a real bug, just
  `src.cache` left half-imported. Full debugging recipe + the t64 trap is in
  `docs/DEVELOPMENT.md` § "What's in `packages.txt`".
