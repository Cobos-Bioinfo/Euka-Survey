import streamlit as st
import sqlite3
import os
import tempfile
import urllib.request
from pathlib import Path
from ete3 import NCBITaxa

# Import local modules securely
from src import taxonomy
from src import visualization
from src import database

# Constants
DB_PATH = "eukaryote_taxid_features_2026_05_08.db"
# Replace with your actual Zenodo or S3 URL when uploaded
DB_DOWNLOAD_URL = "https://zenodo.org/records/20081452/files/eukaryote_taxid_features_2026_05_08.db?download=1" 



st.set_page_config(page_title="EukaSurvey Platform", page_icon="🧬", layout="wide")

@st.cache_resource(show_spinner="Downloading Database (this happens once)...")
def ensure_database():
    """Ensure the SQLite DB exists, downloading it if necessary."""
    if not os.path.exists(DB_PATH):
        st.warning(f"Database not found. Downloading from {DB_DOWNLOAD_URL}...")
        try:
            urllib.request.urlretrieve(DB_DOWNLOAD_URL, DB_PATH)
            st.success("Database downloaded successfully!")
        except Exception as e:
            st.error(f"Could not download database: {e}")
            # Return False so the app knows it's not ready
            return False
    return True

@st.cache_resource
def get_db_connection():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)

def get_ncbi():
    return NCBITaxa()

import multiprocessing as mp

def render_tree_in_process(phylum_metadata, include_counts, out_svg):
    """
    ETE3 requires PyQt5 to render trees. PyQt5 STRICTLY requires its QApplication
    to be created in the main thread of a process. Since Streamlit runs user code
    in worker threads, we must launch a separate process to render the tree.
    """
    # Initialize virtual display for headless environments (Streamlit Cloud)
    try:
        from pyvirtualdisplay import Display
        display = Display(visible=False, size=(1200, 1000))
        display.start()
    except ImportError:
        display = None

    import src.visualization as visualization
    from ete3 import NCBITaxa
    import os
    import shutil

    # Refresh phylo temp directory exclusively for this process
    if os.path.exists(visualization.TMP_DIR):
        shutil.rmtree(visualization.TMP_DIR)
    os.makedirs(visualization.TMP_DIR)

    ncbi = NCBITaxa()
    layout_fn = visualization.create_layout_fn(ncbi, phylum_metadata, include_counts)
    ts = visualization.configure_tree_style(layout_fn, include_counts)
    
    tree = ncbi.get_topology(list(phylum_metadata.keys()))
    tree.render(out_svg, w=1200, units="px", tree_style=ts)

    if display:
        display.stop()


@st.cache_data(show_spinner=False)
def _compute_single_clade(_conn, taxid, min_organisms, exclude_empty):
    """
    Cached helper to quickly fetch pre-computed clade aggregations from SQLite.
    """
    cursor = _conn.cursor()
    cursor.execute("SELECT n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng FROM precomputed_clade_features WHERE taxid = ?", (int(taxid),))
    row = cursor.fetchone()
    
    if not row:
        # If taxid has no entries in precomputed_clade_features (meaning it's fully empty)
        if exclude_empty or min_organisms > 0:
            return None
        return {
            'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
            's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
            'p_ass': 0.0, 'p_ann': 0.0, 'p_rna': 0.0, 'p_lng': 0.0
        }
        
    n = row[0]
    if n < min_organisms:
        return None
        
    c_ass, c_ann, c_rna, c_lng = row[1], row[2], row[3], row[4]
    s_ass, s_ann, s_rna, s_lng = row[5], row[6], row[7], row[8]
    
    if exclude_empty and c_ass == 0 and c_ann == 0 and c_rna == 0 and c_lng == 0:
        return None
        
    # Calculate percentages exactly like before
    p_ass = c_ass / n * 100 if n else 0
    p_ann = c_ann / n * 100 if n else 0
    p_rna = c_rna / n * 100 if n else 0
    p_lng = c_lng / n * 100 if n else 0
    
    return {
        'n_rows': n,
        'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
        's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
        'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
    }


def build_phylum_metadata(conn, taxids, min_organisms=0, exclude_empty=False, progress_bar=None, status_text=None):
    """
    In-memory replacement for phylo_divbarchart.load_data().
    Instead of iterating TSV files, it uses the database directly.
    """
    phylum_metadata = {}
    
    total = len(taxids)
    for i, taxid in enumerate(taxids):
        if status_text:
            status_text.text(f"Processing clade {i+1} of {total} (TaxID {taxid})...")
        if progress_bar:
            progress_bar.progress((i + 1) / total)

        meta = _compute_single_clade(conn, taxid, min_organisms, exclude_empty)
        if meta is not None:
            phylum_metadata[taxid] = meta
            
    return phylum_metadata


def main():
    st.title("EukaSurvey: Phylogenetic Resource Explorer")
    st.markdown("Instantly visualize genomic data availability across the eukaryotic tree of life.")
    
    # 1. Initialize dependencies
    db_ok = ensure_database()
    if not db_ok and not os.path.exists(DB_PATH):
        st.stop()
        
    conn = get_db_connection()
    ncbi = get_ncbi()
    
    # 2. Sidebar Configuration
    st.sidebar.header("Query Configuration")
    root_taxid = st.sidebar.number_input("Root Taxon ID (e.g., 2759 for Eukaryotes)", value=2759, step=1)
    
    target_rank = st.sidebar.selectbox("Breakdown by Rank", ["phylum", "class", "order", "family", "genus"], index=3)
    
    st.sidebar.subheader("Visualization Settings")
    min_organisms = st.sidebar.number_input("Minimum Organisms in Clade", value=0, step=1)
    exclude_empty = st.sidebar.checkbox("Exclude Empty Taxa", value=True)
    include_counts = st.sidebar.checkbox("Show Numeric Details in Tree", value=True)
    
    if st.sidebar.button("Generate Visualization", type="primary"):
        with st.spinner("Finding taxa..."):
            # A) Find all child taxids at the target rank
            taxa_pairs = taxonomy.get_taxa_at_rank(root_taxid, target_rank)
            query_taxids = [t[0] for t in taxa_pairs]
            
            if not query_taxids:
                st.error(f"No {target_rank}s found under TaxID {root_taxid}.")
                st.stop()
                
        with st.spinner(f"Aggregating data for {len(query_taxids)} clades..."):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # B) Fetch data for all found taxids
            phylum_metadata = build_phylum_metadata(conn, query_taxids, min_organisms, exclude_empty, progress_bar, status_text)
            
            progress_bar.empty()
            status_text.empty()
            
            if not phylum_metadata:
                st.warning("No clades have data matching the criteria (or all were empty).")
                st.stop()

        with st.spinner("Rendering phylogenetic tree..."):
            # C) Build and render ETE3 tree map using a Subprocess to respect PyQt threading rules
            tmp_svg = "temp_tree_render.svg"
            if os.path.exists(tmp_svg):
                os.remove(tmp_svg)
                
            ctx = mp.get_context('spawn')
            p = ctx.Process(target=render_tree_in_process, args=(phylum_metadata, include_counts, tmp_svg))
            p.start()
            p.join()
            
            if p.exitcode != 0 or not os.path.exists(tmp_svg):
                st.error("Failed to render the tree. This is usually due to Qt/X11 rendering restrictions.")
                st.stop()
            
            st.image(tmp_svg, use_container_width=True)
            
            # Export button
            with open(tmp_svg, "rb") as f:
                st.download_button(
                    label="Download SVG Tree",
                    data=f.read(),
                    file_name=f"tree_{root_taxid}_{target_rank}.svg",
                    mime="image/svg+xml"
                )

if __name__ == '__main__':
    main()

