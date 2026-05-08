#!/usr/bin/env python3

import sys
import sqlite3
from pathlib import Path

# Add project root to path so we can import src.ete_utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ete_utils import get_species_and_subspecies

EUKARYOTE_TXID = 2759

def patch_database(db_path: Path):
    print(f"Fetching all Eukaryote leaf taxids via ete3 (including subspecies/variants)...")
    # We should include subspecies else they might get dropped since some assemblies/reads might be pinned to a subspecies
    # Eukaryota is massive, fetching might take ~10-20 seconds.
    all_taxids = set(get_species_and_subspecies(EUKARYOTE_TXID, include_subspecies=True))
    print(f"Found {len(all_taxids)} overall Eukaryote leaf taxa (species + subspecies).")

    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    
    # Get existing
    cursor = conn.cursor()
    cursor.execute("SELECT taxid FROM taxid_features")
    existing_taxids = set(row[0] for row in cursor.fetchall())
    print(f"Database currently has {len(existing_taxids)} leaf records with data.")

    missing_taxids = all_taxids - existing_taxids
    print(f"Injecting {len(missing_taxids)} absent taxids with 0 counts into taxid_features...")

    rows = [(taxid, 0, 0, 0, 0) for taxid in missing_taxids]
    
    conn.executemany(
        """
        INSERT OR IGNORE INTO taxid_features
            (taxid, short_read_count, long_read_count, assembly_count, annotation_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    print("Patch complete! Run db_builder/precompute_aggregations.py again.")

if __name__ == "__main__":
    db = Path("eukaryote_taxid_features_2026_05_05.db")
    patch_database(db)
