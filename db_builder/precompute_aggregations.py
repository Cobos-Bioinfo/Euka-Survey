import sqlite3
from pathlib import Path
from collections import defaultdict
from ete3 import NCBITaxa
import time

def precompute_clades(db_path: Path):
    """
    Reads the leaf-level 'taxid_features' table, calculates the aggregations 
    for every ancestral clade, and creates a fast precomputed table.
    """
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    ncbi = NCBITaxa()

    # Get all leaf features
    cursor = conn.cursor()
    cursor.execute("SELECT taxid, short_read_count, long_read_count, assembly_count, annotation_count FROM taxid_features")
    leaf_rows = cursor.fetchall()
    print(f"Loaded {len(leaf_rows)} leaf rows with features.")

    # Dictionary to hold the aggregations for each ancestor
    # Structure: clade_taxid -> {'n_rows', 'c_ass', 'c_ann', 'c_rna', 'c_lng', 's_ass', 's_ann', 's_rna', 's_lng'}
    clade_aggs = defaultdict(lambda: {
        'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
        's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0
    })

    print("Rolling up lineages (this will take a moment)...")
    start_time = time.time()
    
    # We want to do a fast lookup of lineages in batch
    all_taxids = [row[0] for row in leaf_rows]
    
    # ETE3 generates warnings for taxids not found, we handle gracefully.
    try:
        lineages = ncbi.get_lineage_translator(all_taxids)
    except KeyError:
        lineages = {}

    missing_lineages = 0

    for row in leaf_rows:
        taxid = row[0]
        s_short, s_long, s_ass, s_ann = row[1], row[2], row[3], row[4]

        # Booleans for organism counts
        has_ass = 1 if s_ass > 0 else 0
        has_ann = 1 if s_ann > 0 else 0
        has_rna = 1 if (s_short > 0 or s_long > 0) else 0
        has_lng = 1 if s_long > 0 else 0

        lineage = lineages.get(taxid, [])
        if not lineage:
            missing_lineages += 1
            lineage = [taxid] # fallback to just itself

        # Add these leaf counts to every ancestor in the lineage
        for ancestor in lineage:
            agg = clade_aggs[ancestor]
            agg['n_rows'] += 1
            agg['c_ass'] += has_ass
            agg['c_ann'] += has_ann
            agg['c_rna'] += has_rna
            agg['c_lng'] += has_lng
            
            agg['s_ass'] += s_ass
            agg['s_ann'] += s_ann
            agg['s_rna'] += s_short + s_long
            agg['s_lng'] += s_long

    if missing_lineages > 0:
        print(f"Warning: {missing_lineages} taxids had no valid taxonomy lineage in ete3 and were skipped.")

    print(f"Precomputed {len(clade_aggs)} distinct clade nodes in {time.time() - start_time:.2f} seconds.")

    print("Writing to precomputed_clade_features table...")
    # Create the optimized table
    conn.execute("DROP TABLE IF EXISTS precomputed_clade_features")
    conn.execute("""
        CREATE TABLE precomputed_clade_features (
            taxid INTEGER PRIMARY KEY,
            n_rows INTEGER,
            c_ass INTEGER,
            c_ann INTEGER,
            c_rna INTEGER,
            c_lng INTEGER,
            s_ass INTEGER,
            s_ann INTEGER,
            s_rna INTEGER,
            s_lng INTEGER
        )
    """)

    insert_rows = [
        (tid, a['n_rows'], a['c_ass'], a['c_ann'], a['c_rna'], a['c_lng'], a['s_ass'], a['s_ann'], a['s_rna'], a['s_lng'])
        for tid, a in clade_aggs.items()
    ]

    conn.executemany("""
        INSERT INTO precomputed_clade_features 
        (taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, insert_rows)

    conn.commit()
    conn.close()
    print("Done! Database is now optimized for the web.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Precompute clade feature aggregations.")
    parser.add_argument("--db", required=True, help="Path to your eukaryotes.db file.")
    args = parser.parse_args()
    precompute_clades(Path(args.db))
