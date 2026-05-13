import sqlite3
from pathlib import Path
import sys
import os

# Add parent directory to sys.path to import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src import taxonomy

def precompute_common_clades(db_path: Path):
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    
    print("Setting up precomputed_taxa table...")
    conn.execute("DROP TABLE IF EXISTS precomputed_taxa")
    conn.execute("""
        CREATE TABLE precomputed_taxa (
            root_taxid INTEGER,
            target_rank TEXT,
            taxid INTEGER,
            name TEXT
        )
    """)
    
    # Create an index for fast lookups
    conn.execute("CREATE INDEX idx_precomputed_taxa ON precomputed_taxa(root_taxid, target_rank)")

    common_taxids = [2759, 33208, 40674, 9443, 4751, 33090]
    ranks = ["phylum", "class", "order", "family", "genus", "species"]
    
    insert_rows = []
    for root in common_taxids:
        for rank in ranks:
            print(f"Fetching {rank} combinations for TaxID {root}...")
            taxa_pairs = taxonomy.get_taxa_at_rank(root, rank)
            for taxid, name in taxa_pairs:
                insert_rows.append((root, rank, taxid, name))
                
    print(f"Inserting {len(insert_rows)} rows into precomputed_taxa...")
    conn.executemany("""
        INSERT INTO precomputed_taxa (root_taxid, target_rank, taxid, name)
        VALUES (?, ?, ?, ?)
    """, insert_rows)
    
    conn.commit()
    conn.close()
    print("Done! Database is now optimized for UI rendering.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Precompute taxa for common clades.")
    parser.add_argument("--db", required=True, help="Path to database.")
    args = parser.parse_args()
    precompute_common_clades(Path(args.db))