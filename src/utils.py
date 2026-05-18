import os
import urllib.request
import io
import csv
import streamlit as st
from src import database

def ensure_database(db_path, download_url):
    """Ensure the SQLite DB exists, downloading it if necessary."""
    if not os.path.exists(db_path):
        try:
            urllib.request.urlretrieve(download_url, db_path)
        except Exception as e:
            st.error(f"Could not download database: {e}")
            return False
    return True

@st.cache_data(show_spinner=False)
def generate_tsv(_conn, query_taxa):
    """
    Generate a TSV string for the given query taxa.
    """
    if not query_taxa:
        return ""
    
    query_taxids = [t[0] for t in query_taxa]
    taxa_names = {t[0]: t[1] for t in query_taxa}
    
    metadata = database.build_phylum_metadata(_conn, query_taxids, exclude_empty=False)
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    
    # Header in snake_case
    writer.writerow([
        "taxon_id", 
        "name", 
        "total_species", 
        "species_with_assemblies", 
        "species_with_annotations", 
        "species_with_rna_seq", 
        "species_with_long_read_rna_seq", 
        "total_assemblies", 
        "total_annotations", 
        "total_rna_seq", 
        "total_long_read_rna_seq"
    ])
    
    for taxid in query_taxids:
        name = taxa_names.get(taxid, "Unknown")
        stats = metadata.get(taxid, {})
        
        # Guard against missing stats implicitly returning missing keys
        writer.writerow([
            taxid,
            name,
            int(stats.get('n_rows', 0)),
            int(stats.get('c_ass', 0)),
            int(stats.get('c_ann', 0)),
            int(stats.get('c_rna', 0)),
            int(stats.get('c_lng', 0)),
            int(stats.get('s_ass', 0)),
            int(stats.get('s_ann', 0)),
            int(stats.get('s_rna', 0)),
            int(stats.get('s_lng', 0))
        ])
        
    return output.getvalue()
