"""
Fetches descendant taxonomic IDs for a given parent taxonomic ID.
Utilizes the local NCBI taxonomy database via the ete3 library.
"""

from ete3 import NCBITaxa
import sqlite3

NCBI = NCBITaxa()
EUKARYOTE_TXID = 2759


def get_species_and_subspecies(parent_taxid: int, include_subspecies: bool = False) -> set[int]:
    """Get all descendant taxonomic IDs of the specified parent taxid that are classified as species, and optionally subspecies, varietas, forma, or strain."""
    if include_subspecies:
        TARGET_RANKS = {"species", "subspecies", "varietas", "forma", "strain"}
    else:
        TARGET_RANKS = {"species"}
    placeholders = ", ".join("?" * len(TARGET_RANKS))

    query = f"""
        WITH RECURSIVE subtree(taxid) AS (
            SELECT taxid FROM species WHERE taxid = ?
            UNION ALL
            SELECT s.taxid FROM species AS s
            JOIN subtree AS t ON s.parent = t.taxid
        )
        SELECT s.taxid FROM subtree AS t
        JOIN species AS s ON s.taxid = t.taxid
        WHERE s.rank IN ({placeholders})
    """

    conn = sqlite3.connect(NCBITaxa().dbfile)
    try:
        result = {row[0] for row in conn.execute(query, [parent_taxid] + list(TARGET_RANKS))}
    finally:
        conn.close()

    return result

def get_name_from_taxid(taxid: int) -> str:
    """Get the scientific name for a given taxonomic ID."""
    ncbi = NCBITaxa()
    names = ncbi.get_taxid_translator([taxid])
    return names.get(taxid, "Unknown")

def get_rank_from_taxid(taxid: int) -> str:
    """Get the taxonomic rank for a given taxonomic ID."""
    ncbi = NCBITaxa()
    ranks = ncbi.get_rank([taxid])
    return ranks.get(taxid, "Unknown")

# =============================================================================
# DEPRECATED FUNCTIONS
# =============================================================================
# These functions are preserved for reference only and are NOT used in the
# current pipeline. Use get_species_and_subspecies() instead.
# =============================================================================

# def get_descendant_taxids(taxid: int) -> list[int]:
#     """Get all descendant taxonomic IDs, including the input taxid and intermediate nodes."""
#     tree_full = NCBI.get_descendant_taxa(parent=taxid, intermediate_nodes=True)
#     return tree_full + [taxid]

# def get_descendant_organisms_taxids(taxid: int) -> list[int]:
#     """Get all descendant organism taxonomic IDs (excludes input taxid and intermediate nodes)."""
#     tree = NCBI.get_descendant_taxa(parent=taxid)
#     return tree