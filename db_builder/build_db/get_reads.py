"""
Queries the EBI ENA portal API to fetch RNA-seq read metadata.
Separates runs into long-read (ONT/PacBio) and short-read taxa.
"""

import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.constants import EUKARYOTE_TXID

ENA_BASE = "https://www.ebi.ac.uk/ena/portal/api/search"
log = logging.getLogger("euka.get_reads")

_LONG_READ_PLATFORMS = {"OXFORD_NANOPORE", "PACBIO_SMRT"}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def fetch_ena_reads() -> tuple[dict[int, int], dict[int, int], int]:
    """Query ENA portal API for RNA-seq runs and count by taxon × platform.

    Returns (long_reads_txids, short_reads_txids, total_record_count).

    Note on format choice: a streaming `format=tsv` + `iter_lines()` was
    tried (Batch 5) but produced ~28% of the rows of the JSON path —
    the TSV endpoint either applies an undocumented row cap or the
    streaming connection is being severed mid-response. Until that's
    diagnosed we use `format=json` + `r.json()` (one POST, full payload
    materialized in memory). For the current ~8 M-row response this is
    a few hundred MB of RAM, which is acceptable for an offline weekly
    pipeline.
    """
    payload = {
        "result": "read_run",
        "query": (
            f'tax_tree({EUKARYOTE_TXID}) AND '
            f'(library_source="transcriptomic" OR library_strategy="rna-seq")'
        ),
        "fields": "tax_id,instrument_platform",
        "format": "json",
        "limit": 0,
    }
    r = requests.post(
        ENA_BASE,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
    )
    r.raise_for_status()

    try:
        data = r.json()
    except requests.exceptions.JSONDecodeError as e:
        # Re-raise so tenacity retries; previously this silently returned
        # empty dicts + count=0 which masked transient failures.
        log.error("Failed to decode JSON from ENA: %s", e)
        raise

    if not data:
        # Empty result is a hard failure — ENA should always return rows
        # for the Eukaryota-rooted RNA-Seq query.
        log.error("ENA returned no rows.")
        raise RuntimeError("empty ENA response")

    txids_count_long_reads: dict[int, int] = {}
    txids_count_short_reads: dict[int, int] = {}

    for record in data:
        try:
            tax_id = int(record.get("tax_id"))
        except (ValueError, TypeError):
            continue

        platform = record.get("instrument_platform", "")
        if platform in _LONG_READ_PLATFORMS:
            txids_count_long_reads[tax_id] = txids_count_long_reads.get(tax_id, 0) + 1
        else:
            txids_count_short_reads[tax_id] = txids_count_short_reads.get(tax_id, 0) + 1

    return txids_count_long_reads, txids_count_short_reads, len(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    long_txids, short_txids, count = fetch_ena_reads()
    log.info(
        "Fetched %d runs (%d long-read taxa, %d short-read taxa).",
        count, len(long_txids), len(short_txids),
    )
    log.info("First 10 long-read: %s", list(long_txids.items())[:10])
    log.info("First 10 short-read: %s", list(short_txids.items())[:10])
