#!/usr/bin/env python3
"""
Functions for querying the SQLite database of precomputed features.
"""

import csv
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from src.ete_utils import get_species_and_subspecies, get_name_from_taxid, get_rank_from_taxid

def build_phylum_metadata(conn, taxids, exclude_empty=False):
    """
    In-memory replacement for phylo_divbarchart.load_data().
    Uses bulk queries to fetch all required metadata at database speeds.
    """
    phylum_metadata = {}
    
    if not taxids:
        return phylum_metadata
        
    cursor = conn.cursor()
    chunk_size = 900 # Safe under SQLite 999 variable limits
    
    for i in range(0, len(taxids), chunk_size):
        chunk = taxids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        
        cursor.execute(f"""
            SELECT taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng 
            FROM precomputed_clade_features 
            WHERE taxid IN ({placeholders})
        """, chunk)
        
        results = {row[0]: row[1:] for row in cursor.fetchall()}
        
        for taxid in chunk:
            row = results.get(int(taxid))
            
            if not row:
                if exclude_empty:
                    continue
                phylum_metadata[taxid] = {
                    'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
                    's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
                    'p_ass': 0.0, 'p_ann': 0.0, 'p_rna': 0.0, 'p_lng': 0.0
                }
                continue
                
            n = row[0]
            c_ass, c_ann, c_rna, c_lng = row[1], row[2], row[3], row[4]
            s_ass, s_ann, s_rna, s_lng = row[5], row[6], row[7], row[8]
            
            if exclude_empty and c_ass == 0 and c_ann == 0 and c_rna == 0 and c_lng == 0:
                continue
                
            p_ass = c_ass / n * 100 if n else 0
            p_ann = c_ann / n * 100 if n else 0
            p_rna = c_rna / n * 100 if n else 0
            p_lng = c_lng / n * 100 if n else 0
            
            phylum_metadata[taxid] = {
                'n_rows': n,
                'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
                's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
                'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
            }
            
    return phylum_metadata


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CladeSummary:
    taxid: int
    name: str
    rank: str
    total_organisms: int
    short_read_count: int
    long_read_count: int
    assembly_count: int
    annotation_count: int
    short_read_orgs: int    # unique organisms with any short reads
    long_read_orgs: int
    assembly_orgs: int
    annotation_orgs: int


# ---------------------------------------------------------------------------
# Database querying
# ---------------------------------------------------------------------------

# Chunk size for IN (...) queries.
# SQLite's default limit is 999 bound variables; 500 is a safe, round number.
_CHUNK_SIZE = 500


def _query_features_chunked(
    conn: sqlite3.Connection, taxids: list[int]
) -> dict[str, int]:
    """
    Query taxid_features for a (potentially large) list of taxIDs and return
    both summed feature counts and per-feature unique organism counts.

    Strategy: split taxids into chunks and use IN (...) per chunk, then
    aggregate in Python. This avoids hitting SQLite's bound-variable limit
    and keeps the code straightforward without needing temporary tables.

    Returns a dict with keys:
        short_read_count, long_read_count, assembly_count, annotation_count
        short_read_orgs, long_read_orgs, assembly_orgs, annotation_orgs
    """
    totals = {
        "short_read_count": 0,
        "long_read_count":  0,
        "assembly_count":   0,
        "annotation_count": 0,
        "short_read_orgs":  0,
        "long_read_orgs":   0,
        "assembly_orgs":    0,
        "annotation_orgs":  0,
    }

    if not taxids:
        return totals

    cursor = conn.cursor()

    for start in range(0, len(taxids), _CHUNK_SIZE):
        chunk = taxids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        sql = f"""
            SELECT
                SUM(short_read_count),
                SUM(long_read_count),
                SUM(assembly_count),
                SUM(annotation_count),
                SUM(CASE WHEN short_read_count  > 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN long_read_count   > 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN assembly_count    > 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN annotation_count  > 0 THEN 1 ELSE 0 END)
            FROM taxid_features
            WHERE taxid IN ({placeholders})
        """
        row = cursor.execute(sql, chunk).fetchone()
        if row:
            totals["short_read_count"] += row[0] or 0
            totals["long_read_count"]  += row[1] or 0
            totals["assembly_count"]   += row[2] or 0
            totals["annotation_count"] += row[3] or 0
            totals["short_read_orgs"]  += row[4] or 0
            totals["long_read_orgs"]   += row[5] or 0
            totals["assembly_orgs"]    += row[6] or 0
            totals["annotation_orgs"]  += row[7] or 0

    return totals


def _query_all_taxid_features(
    conn: sqlite3.Connection, taxids: list[int]
) -> dict[int, tuple[int, int, int, int]]:
    """
    Fetch raw feature counts for each taxID that exists in the DB.

    Returns a dict: {taxid: (short_read_count, long_read_count, assembly_count, annotation_count)}
    TaxIDs absent from the DB are not included (caller should default to zeros).
    """
    result: dict[int, tuple[int, int, int, int]] = {}
    cursor = conn.cursor()

    for start in range(0, len(taxids), _CHUNK_SIZE):
        chunk = taxids[start : start + _CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        sql = f"""
            SELECT taxid, short_read_count, long_read_count, assembly_count, annotation_count
            FROM taxid_features
            WHERE taxid IN ({placeholders})
        """
        for row in cursor.execute(sql, chunk):
            result[row[0]] = (row[1], row[2], row[3], row[4])

    return result


def summarize_clade(
    conn: sqlite3.Connection, taxid: int, include_subspecies: bool = False
) -> tuple["CladeSummary", list[int]]:
    """
    Expand a clade to its descendant taxIDs, then query the DB for feature
    counts. TaxIDs absent from the DB contribute 0 to all sums.

    Returns (CladeSummary, descendants) — descendants are returned so the
    caller can reuse them for TSV export without re-expanding the clade.
    """
    descendants = list(get_species_and_subspecies(taxid, include_subspecies=include_subspecies))
    total_organisms = len(descendants)

    feature_counts = _query_features_chunked(conn, descendants)

    summary = CladeSummary(
        taxid=taxid,
        name=get_name_from_taxid(taxid),
        rank=get_rank_from_taxid(taxid),
        total_organisms=total_organisms,
        **feature_counts,
    )
    return summary, descendants


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _pct(count: int, total: int) -> str:
    if total == 0:
        return "  n/a"
    return f"{count / total * 100:5.1f}%"


def print_summary(summary: CladeSummary) -> None:
    t = summary.total_organisms
    rows = [
        ("short_reads", summary.short_read_count, summary.short_read_orgs),
        ("long_reads",  summary.long_read_count,  summary.long_read_orgs),
        ("assemblies",  summary.assembly_count,   summary.assembly_orgs),
        ("annotations", summary.annotation_count, summary.annotation_orgs),
    ]

    print(f"\n{summary.name} [{summary.rank}] — TaxID {summary.taxid}")
    print(f"  {'total_organisms':<18}: {t:>10,}")
    for label, total_count, unique_orgs in rows:
        print(
            f"  {label:<18}: {total_count:>10,} total"
            f"  |  {unique_orgs:>8,} organisms  ({_pct(unique_orgs, t)})"
        )


# ---------------------------------------------------------------------------
# TSV export
# ---------------------------------------------------------------------------

_TSV_FIELDS = [
    "taxid", "short_read_count", "long_read_count", "assembly_count", "annotation_count"
]


def write_tsv(
    summary: CladeSummary,
    descendants: list[int],
    feature_rows: dict[int, tuple[int, int, int, int]],
    tsv_dir: str,
    include_empty: bool = False,
) -> str:
    """
    Write one TSV file for a clade: one row per descendant taxID.

    By default, taxIDs absent from the DB (all counts zero) are omitted.
    Pass include_empty=True to write a row for every descendant regardless.

    Returns the path of the written file.
    """
    safe_name = summary.name.replace(" ", "_")
    filename = f"{summary.taxid}_{safe_name}.tsv"
    filepath = Path(tsv_dir) / filename

    with open(filepath, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_TSV_FIELDS, delimiter="\t")
        writer.writeheader()
        for taxid in sorted(descendants):
            counts = feature_rows.get(taxid, (0, 0, 0, 0))
            if not include_empty and counts == (0, 0, 0, 0):
                continue
            writer.writerow({
                "taxid":            taxid,
                "short_read_count": counts[0],
                "long_read_count":  counts[1],
                "assembly_count":   counts[2],
                "annotation_count": counts[3],
            })

    return str(filepath)
