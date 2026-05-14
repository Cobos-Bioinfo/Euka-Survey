#!/usr/bin/env python3
"""
get_taxa_by_rank.py — Get all taxIDs of a given rank under a clade.
"""

from ete3 import NCBITaxa


def get_taxa_at_rank(root_taxid: int, rank: str) -> list[tuple[int, str]]:
    """Return all (taxid, name) pairs at the given rank under root_taxid."""
    ncbi = NCBITaxa()
    descendants = ncbi.get_descendant_taxa(root_taxid, intermediate_nodes=True)
    ranks = ncbi.get_rank(descendants)
    hits = [taxid for taxid, r in ranks.items() if r == rank]
    names = ncbi.get_taxid_translator(hits)
    return sorted(names.items(), key=lambda x: x[1])  # sort by name
