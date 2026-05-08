"""
Handles the construction and population of the local SQLite database.
Aggregates dictionaries of taxonomic IDs -> counts (assemblies, reads, annotations) into a table.
"""

import sqlite3
from pathlib import Path


def build_database(
    all_taxids: set[int],
    assembly_taxids: dict[int, int],
    annotation_taxids: dict[int, int],
    short_read_taxids: dict[int, int],
    long_read_taxids: dict[int, int],
    db_path: Path,
) -> int:
    """
    Build (or update) the SQLite database from source dictionaries.

    Uses all known leaf taxids so that 'Total Organisms' properly counts every 
    species/leaf node, even those entirely missing data.
    Uses INSERT OR REPLACE so this is safe to re-run incrementally.

    Returns the number of rows written.
    """
    featured_taxids: set[int] = (
        all_taxids
        | assembly_taxids.keys()
        | annotation_taxids.keys()
        | short_read_taxids.keys()
        | long_read_taxids.keys()
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS taxid_features (
                taxid              INTEGER PRIMARY KEY,
                short_read_count   INTEGER NOT NULL DEFAULT 0,
                long_read_count    INTEGER NOT NULL DEFAULT 0,
                assembly_count     INTEGER NOT NULL DEFAULT 0,
                annotation_count   INTEGER NOT NULL DEFAULT 0
            )
        """)

        rows: list[tuple[int, int, int, int, int]] = [
            (
                taxid,
                short_read_taxids.get(taxid, 0),
                long_read_taxids.get(taxid, 0),
                assembly_taxids.get(taxid, 0),
                annotation_taxids.get(taxid, 0),
            )
            for taxid in featured_taxids
        ]

        conn.executemany(
            """
            INSERT OR REPLACE INTO taxid_features
                (taxid, short_read_count, long_read_count, assembly_count, annotation_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    return len(rows)
