#!/usr/bin/env python3
"""
pipeline_build_db.py — Build a SQLite database of taxIDs with assemblies, annotations, and reads.
"""

import sys
import time
import datetime
from pathlib import Path

# Add project root to path so we can import src and db_builder modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ete_utils import get_species_and_subspecies

from db_builder.build_db.get_assemblies import get_assemblies
from db_builder.build_db.get_annotations import fetch_annotrieve_annotations
from db_builder.build_db.get_reads import fetch_ena_reads
from db_builder.build_db.build_database import build_database

EUKARYOTE_TXID = 2759


def main():
    print("--- Starting Eukaryote Feature Pipeline ---")
    start_time = time.time()

    # 1. Get all taxonomic IDs
    print("\n[1/5] Getting all descendant organisms...")
    print("Fetching descendant organisms from NCBI via ete3...")
    # We include subspecies to ensure full coverage of strains/subspecies in lineage representations.
    all_taxids = set(get_species_and_subspecies(EUKARYOTE_TXID, include_subspecies=True))
    print(f"  Found {len(all_taxids)} tree leaves (species, subspecies, varietas, forma, strain) under Eukaryota (taxid {EUKARYOTE_TXID})")
    
    # 2. Get assemblies
    print("\n[2/5] Getting assembly taxids...")
    print("Fetching assemblies using NCBI datasets CLI...")
    assembly_taxids = get_assemblies(EUKARYOTE_TXID)
    print(f"  Found assemblies for {len(assembly_taxids)} unique taxa")
    
    # 3. Get annotations
    print("\n[3/5] Getting annotation taxids...")
    print("Fetching annotations from Annotrieve...")
    annotation_taxids = fetch_annotrieve_annotations()
    print(f"  Found annotations for {len(annotation_taxids)} taxa")
    
    # 4. Get reads
    print("\n[4/5] Getting short and long read taxids...")
    print("Fetching ENA RNA-seq reads...")
    long_read_taxids, short_read_taxids, count = fetch_ena_reads()
    print(f"  Fetched {count} runs")
    print(f"  Long-read unique taxa: {len(long_read_taxids)}")
    print(f"  Short-read unique taxa: {len(short_read_taxids)}")
    if 9606 not in short_read_taxids.keys() or 10090 not in short_read_taxids.keys():
        print(f"  [WARNING] Humans (9606) and mice (10090) were excluded from the query to greatly reduce the number of records")
    
    # 5. Build database
    print("\n[5/5] Building SQLite database...")
    today_str = datetime.date.today().strftime("%Y_%m_%d")
    output_db = Path(f"eukaryote_taxid_features_{today_str}.db")
    print(f"Saving records to {output_db.name}...")
    
    rows_written = build_database(
        all_taxids=all_taxids,
        assembly_taxids=assembly_taxids,
        annotation_taxids=annotation_taxids,
        short_read_taxids=short_read_taxids,
        long_read_taxids=long_read_taxids,
        db_path=output_db
    )
    
    print("\n[6/6] Precomputing clade aggregations for web app...")
    from db_builder.precompute_aggregations import precompute_clades
    precompute_clades(output_db)
    
    elapsed = time.time() - start_time
    print(f"\nPipeline completed successfully in {elapsed:.2f} seconds.")
    print(f"Wrote {rows_written} records to {output_db.name}.")

if __name__ == "__main__":
    main()
