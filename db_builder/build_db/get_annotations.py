"""
Fetches taxonomic IDs that have functional annotations.
Queries the Annotrieve API frequency endpoint to filter annotated taxa.
"""

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

ANNOTRIEVE_BASE = "https://genome.crg.es/annotrieve/api/v0"

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def fetch_annotrieve_annotations() -> dict[int, int]:
    """Get all taxids with annotations and return as a dictionary of taxid to annotation count."""
    url = f"{ANNOTRIEVE_BASE}/annotations/frequencies/taxid"
    r = requests.get(url, headers={"Content-Type": "application/json"}, timeout=120)
    r.raise_for_status()
    data = r.json()
    taxids_count_annotations: dict[int, int] = dict()
    for tid_str, count in data.items():
        try:
            taxids_count_annotations[int(tid_str)] = count
        except (ValueError, TypeError):
            pass
    return taxids_count_annotations

if __name__ == "__main__":
    fetch_annotrieve_annotations()
