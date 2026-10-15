"""ETE3-backed taxonomy lookups.

Thin helpers over `ete3.NCBITaxa` for name/rank lookups, plus a direct
recursive-CTE query against ETE3's underlying SQLite taxonomy database for
bulk descendant collection (used by the offline pipeline).
"""

import sqlite3
import threading
from contextlib import closing
from functools import lru_cache

from ete3 import NCBITaxa
from ete3.ncbi_taxonomy.ncbiquery import DEFAULT_TAXADB

# Where `NCBITaxa()` looks for its taxonomy DB (and builds it from taxdump if
# absent). The app pre-seeds this path via `utils.ensure_taxonomy_database`.
TAXA_DB_PATH: str = DEFAULT_TAXADB


# Thread-local NCBITaxa cache.
#
# ETE3's NCBITaxa holds a sqlite3.Connection (default check_same_thread=True),
# so it cannot be shared across worker threads. Streamlit dispatches
# callbacks across an internal worker pool, which used to make every
# rerun call `NCBITaxa()` 5+ times — opening fresh SQLite handles each
# time. A `threading.local` cache collapses that to one instance per
# thread for the process lifetime, without breaking thread safety.
#
# A pure module-level singleton was considered and rejected (audit
# H4 / Top 10 #2 "PARTIAL/BLOCKED by Streamlit thread-affinity").
_TLS = threading.local()


def get_ncbi() -> NCBITaxa:
    """Return the calling thread's cached `NCBITaxa` instance.

    Lazy-initialises on first call per thread. The instance lives as
    long as the thread does (i.e. the whole Streamlit worker lifetime).
    """
    if not hasattr(_TLS, "ncbi"):
        _TLS.ncbi = NCBITaxa()
    return _TLS.ncbi


@lru_cache(maxsize=4096)
def get_name_from_taxid(taxid: int) -> str:
    """Get the scientific name for a given taxonomic ID, or "Unknown"."""
    if not isinstance(taxid, int):
        return "Unknown"
    return get_ncbi().get_taxid_translator([taxid]).get(taxid, "Unknown")


@lru_cache(maxsize=4096)
def get_rank_from_taxid(taxid: int) -> str:
    """Get the taxonomic rank for a given taxonomic ID, or "clade"."""
    if not isinstance(taxid, int):
        return "clade"
    return get_ncbi().get_rank([taxid]).get(taxid, "clade")


def get_all_descendant_taxids(parent_taxid: int) -> set[int]:
    """Fetch all descendant taxIDs of `parent_taxid` directly from ETE3's SQLite db."""
    query = """
        WITH RECURSIVE subtree(taxid) AS (
            SELECT taxid FROM species WHERE taxid = ?
            UNION ALL
            SELECT s.taxid FROM species AS s
            JOIN subtree AS t ON s.parent = t.taxid
        )
        SELECT taxid FROM subtree
    """
    db_path = get_ncbi().dbfile
    uri = f"file:{db_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return {row[0] for row in conn.execute(query, [parent_taxid])}
