"""
Retrieves assembly information for taxonomic IDs.
Uses the NCBI datasets CLI to identify which taxa have sequenced genome assemblies.
"""

import subprocess
import sys
import json

EUKARYOTE_TXID = 2759

def get_assemblies(txid: int) -> dict[int, int]:
    """Get a dictionary of taxonomic IDs and their assembly counts using NCBI datasets CLI tool."""
    try:
        process = subprocess.Popen(
            [
                "datasets",
                "summary",
                "genome",
                "taxon",
                str(txid),
                "--as-json-lines"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print(
            "Error: NCBI datasets CLI not found. Install from: "
            "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/command-line-tools/download-and-install/",
            file=sys.stderr,
        )
        sys.exit(1)
        
    taxids_count_assembly: dict[int, int] = dict()
    
    # Read the output line by line, parse JSON, and extract taxonomic IDs
    for line in process.stdout: # type: ignore
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            organism = record.get("organism") or {}
            tax_id = organism.get("tax_id")
            if tax_id is None:
                continue
            taxids_count_assembly[tax_id] = taxids_count_assembly.get(tax_id, 0) + 1

        except json.JSONDecodeError as e:
            print(f"Warning: skipping malformed record: {e}", file=sys.stderr)

    process.wait()

    if process.returncode != 0: 
        stderr_output = process.stderr.read().strip() # type: ignore
        print(f"Error: datasets exited with code {process.returncode}: {stderr_output}", file=sys.stderr)
        sys.exit(1)

    return taxids_count_assembly

if __name__ == "__main__":
    # Example usage
    txid_assemblies = get_assemblies(EUKARYOTE_TXID)
    print(f"Total taxonomic IDs with assemblies: {len(txid_assemblies)}")
    print(list(txid_assemblies.items())[:10])
