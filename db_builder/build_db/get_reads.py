"""
Queries the EBI ENA portal API to fetch RNA-seq read metadata.
Separates runs into long-read (ONT/PacBio) and short-read taxa.
"""

import json
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

EUKARYOTE_TXID = 2759
ENA_BASE = "https://www.ebi.ac.uk/ena/portal/api/search"

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def _ena_search() -> tuple[dict[int, int], dict[int, int], int]:
    """Query ENA portal API (POST) for RNA-seq reads. Limit=0 fetches all records in one request."""
    payload = {
        "result": "read_run",
        "query": f'tax_tree({EUKARYOTE_TXID}) AND library_strategy="rna-seq"',
        "fields": "tax_id,instrument_platform",
        "format": "json",
        "limit": 0,
        "excludeAccessionType": "taxon",
        "excludeAccessions": "9606,10090"  # Exclude human and mouse to greatly reduce the number of records
    }
    r = requests.post(
        ENA_BASE,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
        stream=True,
    )
    r.raise_for_status()
    
    try:
        data = r.json()
    except requests.exceptions.JSONDecodeError as e:
        print(f"Failed to decode JSON from ENA: {e}")
        return dict(), dict(), 0

    txids_count_long_reads: dict[int, int] = dict()
    txids_count_short_reads: dict[int, int] = dict()

    for record in data:
        try:
            tax_id = int(record.get("tax_id"))
        except (ValueError, TypeError):
            continue
            
        platform = record.get("instrument_platform", "")
        if platform in ("OXFORD_NANOPORE", "PACBIO_SMRT"):
            txids_count_long_reads[tax_id] = txids_count_long_reads.get(tax_id, 0) + 1
        else:
            txids_count_short_reads[tax_id] = txids_count_short_reads.get(tax_id, 0) + 1

    return txids_count_long_reads, txids_count_short_reads, len(data)


def fetch_ena_reads() -> tuple[dict[int, int], dict[int, int], int]:
    """
    Fetch ENA RNA-seq reads. Returns two dictionaries of taxids and their read counts, and the total record count:
    (long_reads_txids, short_reads_txids, count).
    """
    long_reads_txids, short_reads_txids, count = _ena_search()
    return long_reads_txids, short_reads_txids, count

if __name__ == "__main__":
    long_txids, short_txids, count = fetch_ena_reads()
    print(f"Verification complete: {count} runs fetched, {len(long_txids)} long-read taxa, {len(short_txids)} short-read taxa.")
    print(f"Sample of long-read taxa and counts: {list(long_txids.items())[:10]}")
    print(f"Sample of short-read taxa and counts: {list(short_txids.items())[:10]}")
    