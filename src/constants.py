"""Shared constants for the EukaSurvey app and db_builder pipeline.

Single source of truth for taxonomic IDs, ranks, and UI limits that were
previously duplicated across app.py, db_builder/precompute_taxa.py, and the
db_builder/build_db/* modules.
"""

# Path used by the Streamlit app to locate (and download into) the
# precomputed DB. Sibling to `eukaryotes.db` on disk; gitignored.
DB_PATH: str = "eukaryotes.db"

# Sidecar file recording the GitHub Release tag of the on-disk DB, so the
# app can tell whether a newer weekly build exists without re-downloading.
# Written by `src/utils.ensure_latest_database`; gitignored (`*.db.version`).
DB_VERSION_PATH: str = DB_PATH + ".version"

# How often a long-running app re-checks GitHub for a newer database release
# (the `ttl` on `cache.get_db_ready`). The DB is rebuilt weekly, so hourly is
# plenty responsive; the check is one cheap Releases-API call per interval.
DB_REFRESH_TTL_SECONDS: int = 3600

# Where the app fetches `eukaryotes.db` from on first run. Points at
# the GitHub Release tagged `latest` — see Batch 10 in the changelog
# for the date-tagged release scheme that keeps this pointer stable.
DB_DOWNLOAD_URL: str = (
    "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/latest/download/eukaryotes.db"
)

EUKARYOTE_TXID: int = 2759

COMMON_CLADES: dict[int, str] = {
    2759: "Eukaryota",
    33208: "Animals",
    40674: "Mammalia",
    9443: "Primates",
    4751: "Fungi",
    33090: "Plants",
}

ALLOWED_RANKS: list[str] = [
    "phylum", "class", "order", "family", "genus", "species",
]

FULL_RANKS: list[str] = [
    "domain", "superkingdom", "kingdom",
    "superphylum", "phylum", "subphylum",
    "superclass", "class", "subclass",
    "superorder", "order", "suborder",
    "superfamily", "family", "subfamily",
    "genus", "subgenus", "species",
]

# Hard ceiling on how many taxa a single tree/table render may include.
# The ETE3 render runs in a spawned subprocess that draws one matplotlib
# bar chart per leaf; very large trees can OOM the ~1 GB Streamlit Cloud
# container. 200 is a safe, still-useful ceiling (was 500, which crashed).
HARD_NODE_CAP: int = 200
STANDARD_BREAKPOINTS: list[int] = [10, 25, 50, 75, 100, 150, 200]

SQLITE_MAX_VARIABLES: int = 999

RENDER_SUBPROCESS_TIMEOUT_SECONDS: int = 120

# TTL for the per-query `@st.cache_data` caches (taxa counts/lists, metadata,
# rendered tree SVG, export TSV). Time-bounds cache memory so a long-lived,
# always-awake app can't accumulate large cached objects until it OOMs — the
# 12h Community-Cloud sleep used to flush caches, but the keepalive bot now
# prevents that sleep, so nothing ever reset them. Also refreshes query results
# within this window after a weekly DB hot-swap (they're keyed on query params,
# not the DB version). 1 hour is well within the weekly rebuild cadence and
# cheap to recompute.
CACHE_TTL_SECONDS: int = 3600

# eukaryotes.db schema version stamped via `PRAGMA user_version`.
#
# The pipeline writes CURRENT on every build. The app reads it on
# startup and refuses to launch against a DB outside the
# [MIN_COMPATIBLE, CURRENT] range.
#
# Bump CURRENT when you make a schema change. Bump MIN_COMPATIBLE only
# when you make a *breaking* change that the app's queries can no
# longer tolerate (rare).
#
# Special case: SQLite's default value is 0. We treat 0 as "legacy
# pre-versioned build" and accept it as equivalent to version 1, so
# existing DBs built before this gate was introduced keep working.
DB_SCHEMA_VERSION_CURRENT: int = 1
DB_SCHEMA_VERSION_MIN_COMPATIBLE: int = 1
DB_SCHEMA_VERSION_LEGACY: int = 0  # unstamped DBs from before this gate
