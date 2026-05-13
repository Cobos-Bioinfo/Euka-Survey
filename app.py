import streamlit as st
import sqlite3
import os
import tempfile
import urllib.request
import multiprocessing as mp
from pathlib import Path
from ete3 import NCBITaxa

# Import local modules securely
from src import taxonomy
from src import visualization
from src import database

# Constants
DB_PATH = "eukaryote_taxid_features_2026_05_11.db" # For local development
# Fetch from the automatic GitHub Release action
DB_DOWNLOAD_URL = "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/latest/download/eukaryotes.db"  


# --- Streamlit Community Cloud App Name ---
st.set_page_config(page_title="EukaSurvey Platform", page_icon="🧬", layout="wide", initial_sidebar_state="expanded")

@st.cache_resource(show_spinner="Downloading Database (this happens once)...")
def ensure_database():
    """Ensure the SQLite DB exists, downloading it if necessary."""
    if not os.path.exists(DB_PATH):
        # st.warning(f"Database not found. Downloading from {DB_DOWNLOAD_URL}...")
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
    
    # Filter valid taxids that exist in local ETE3 database
    valid_taxids = []
    for tid in phylum_metadata.keys():
        try:
            ncbi.get_lineage(tid)
            valid_taxids.append(tid)
        except ValueError:
            pass
            
    if not valid_taxids:
        if display:
            display.stop()
        return

    layout_fn = visualization.create_layout_fn(ncbi, phylum_metadata, include_counts)
    ts = visualization.configure_tree_style(layout_fn, include_counts)
    
    tree = ncbi.get_topology(valid_taxids)
    tree.render(out_svg, w=1200, units="px", tree_style=ts)

    if display:
        display.stop()


def build_phylum_metadata(conn, taxids, exclude_empty=False):
    """
    In-memory replacement for phylo_divbarchart.load_data().
    Uses bulk queries to fetch all required metadata at database speeds.
    """
    phylum_metadata = {}
    
    if not taxids:
        return phylum_metadata
        
    cursor = conn.cursor()
    chunk_size = 900 # Safe under SQLite 999 variable limits
    
    for i in range(0, len(taxids), chunk_size):
        chunk = taxids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        
        cursor.execute(f"""
            SELECT taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng 
            FROM precomputed_clade_features 
            WHERE taxid IN ({placeholders})
        """, chunk)
        
        results = {row[0]: row[1:] for row in cursor.fetchall()}
        
        for taxid in chunk:
            row = results.get(int(taxid))
            
            if not row:
                if exclude_empty:
                    continue
                phylum_metadata[taxid] = {
                    'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
                    's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
                    'p_ass': 0.0, 'p_ann': 0.0, 'p_rna': 0.0, 'p_lng': 0.0
                }
                continue
                
            n = row[0]
            c_ass, c_ann, c_rna, c_lng = row[1], row[2], row[3], row[4]
            s_ass, s_ann, s_rna, s_lng = row[5], row[6], row[7], row[8]
            
            if exclude_empty and c_ass == 0 and c_ann == 0 and c_rna == 0 and c_lng == 0:
                continue
                
            p_ass = c_ass / n * 100 if n else 0
            p_ann = c_ann / n * 100 if n else 0
            p_rna = c_rna / n * 100 if n else 0
            p_lng = c_lng / n * 100 if n else 0
            
            phylum_metadata[taxid] = {
                'n_rows': n,
                'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
                's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
                'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
            }
            
    return phylum_metadata

@st.cache_data(show_spinner=False)
def _fetch_taxa_ete3_fallback(root_taxid, target_rank):
    """Fallback to ETE3 if not precomputed."""
    return taxonomy.get_taxa_at_rank(root_taxid, target_rank)

def fetch_taxa_cached(conn, root_taxid, target_rank):
    """Fetch taxa from DB if precomputed, safely falling back to ETE3."""
    if root_taxid is None or target_rank is None:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT taxid, name FROM precomputed_taxa WHERE root_taxid = ? AND target_rank = ?", (int(root_taxid), target_rank))
        rows = cursor.fetchall()
        if rows:
            return [(row[0], row[1]) for row in rows]
    except sqlite3.OperationalError:
        pass  # Table might not exist yet
        
    return _fetch_taxa_ete3_fallback(root_taxid, target_rank)

def main():
    st.title("EukaSurvey: The Genomic Resource Explorer for Eukaryotes")
    st.markdown("Visualize genomic data availability across the Eukaryotic Tree of Life.")
    
    # 1. Initialize dependencies
    db_ok = ensure_database()
    if not db_ok:
        st.stop()
         
    conn = get_db_connection()
    ncbi = get_ncbi()
    
    ##### 2. Sidebar Configuration #####
    st.sidebar.header("Query Configuration")
    
    # Root taxon selection with common clades for convenience
    common_taxa = ["Eukaryota (2759)", "Animals (33208)", "Mammalia (40674)", "Primates (9443)", "Fungi (4751)", "Plants (33090)"]
    
    choice = st.sidebar.selectbox(
        "Set a custom Root Taxon ID or explore commonly surveyed clades:", 
        ["Enter your own"] + common_taxa,
        index=None,  # Nothing selected by default
        placeholder="Choose a valid NCBI Taxon ID"
    )

    # Handle the selection
    if choice is None:
        root_taxid = None
    elif choice == "Enter your own":
        root_taxid = st.sidebar.text_input("Enter a valid NCBI Taxon ID", label_visibility="collapsed")
        if root_taxid.isdigit():
            root_taxid = int(root_taxid)
        else:
            st.sidebar.warning("Please enter a valid numeric Taxon ID.")
    else:
        taxid_map = {"Eukaryota (2759)": 2759, "Animals (33208)": 33208, "Mammalia (40674)": 40674, "Primates (9443)": 9443, "Fungi (4751)": 4751, "Plants (33090)": 33090}
        root_taxid = taxid_map[choice]
    
    # Target rank selection
    target_rank = st.sidebar.selectbox("Breakdown by Rank", ["phylum", "class", "order", "family", "genus", "species"], placeholder=None)
    
    # Pre-fetch taxa to provide reactive feedback on tree size
    query_taxids = []
    num_nodes = 0
    if root_taxid and target_rank:
        query_taxa = fetch_taxa_cached(conn, root_taxid, target_rank)
        if query_taxa:
            query_taxids = [t[0] for t in query_taxa]
            num_nodes = len(query_taxids)
            st.sidebar.info(f"Tree size: **{num_nodes}** {target_rank} nodes")
            if num_nodes > 100:
                st.sidebar.warning("High node counts may take longer to compute and render.")
        else:
            st.sidebar.warning(f"No {target_rank}s found under TaxID {root_taxid}.")

    # Visualization settings
    st.sidebar.subheader("Visualization Settings")
    sort_options = {
        "Number of organisms": "n_rows",
        "Number of Assemblies": "c_ass",
        "Annotations": "c_ann",
        "RNA-Seq (Any)": "c_rna",
        "Long-Read RNA": "c_lng"
    }
    sort_by_label = st.sidebar.selectbox("Sort by", list(sort_options.keys()))
    sort_by_key = sort_options[sort_by_label]
    
    if num_nodes > 2:
        top_n = st.sidebar.slider("Max nodes to display", min_value=2, max_value=num_nodes, value=min(50, num_nodes))
    else:
        top_n = max(2, num_nodes)
    
    exclude_empty = st.sidebar.checkbox("Exclude Empty Taxa", value=True)
    include_counts = st.sidebar.checkbox("Show Numeric Details in Tree", value=True)

    if st.sidebar.button("Generate Visualization", type="primary"):
        if not query_taxids:
            st.error(f"Cannot generate tree. No {target_rank}s found or invalid TaxID {root_taxid}.")
            st.stop()
            
        with st.spinner(f"Aggregating data for {top_n} clades..."):
            
            # B) Fetch data for all found taxids
            phylum_metadata = build_phylum_metadata(conn, query_taxids, exclude_empty)
            
            # Sort and subset to Top N
            if phylum_metadata:
                if sort_by_key.startswith('c_'):
                    s_key = sort_by_key.replace('c_', 's_')
                    sorted_items = sorted(phylum_metadata.items(), key=lambda x: (x[1][sort_by_key], x[1][s_key]), reverse=True)
                else:
                    sorted_items = sorted(phylum_metadata.items(), key=lambda x: (x[1][sort_by_key], x[1]['c_ass']), reverse=True)
                phylum_metadata = dict(sorted_items[:top_n])
            
            # Show exclusion statistics
            nodes_excluded = len(query_taxids) - len(phylum_metadata)
            if nodes_excluded > 0:
                st.info(f"**Nodes included:** {len(phylum_metadata)}/{len(query_taxids)} "
                        f"({nodes_excluded} excluded due to filtering criteria)")
            
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
            
            # Store success in session state to persist buttons
            st.session_state.rendered_taxid = root_taxid
    
    
    # --- Open Query-Specific Database Buttons --- #
    if "rendered_taxid" in st.session_state:
        st.divider()
        st.header("Explore Primary Databases")
        taxid = st.session_state.rendered_taxid
        root_name = ncbi.get_taxid_translator([taxid]).get(taxid, "Unknown Taxon")
        
        with st.container(horizontal=True, gap="medium"):
            cols = st.columns(3, gap="medium", width="stretch", border=True)
            
            with cols[0]:
                st.subheader("ENA Browser", text_alignment="center")
                ena_url = f"https://www.ebi.ac.uk/ena/browser/advanced-search?result=read_run&query=tax_tree({taxid})%20AND%20library_strategy%3D%22rna-seq%22&fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy&limit=0"
                st.markdown(f'<a href="{ena_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #18974c; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open RNA-Seq Reads for {root_name}</a>', unsafe_allow_html=True)

            with cols[1]:
                st.subheader("NCBI Datasets", text_alignment="center")
                ncbi_url = f"https://www.ncbi.nlm.nih.gov/datasets/genome/?taxon={taxid}"
                st.markdown(f'<a href="{ncbi_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #20558a; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open Genome Assemblies for {root_name}</a>', unsafe_allow_html=True)

            with cols[2]:
                st.subheader("Annotrieve", text_alignment="center")
                anno_url = f"https://genome.crg.es/annotrieve/annotations/details/?taxon={taxid}"
                st.markdown(f'<a href="{anno_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #f07900; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open Annotations for {root_name}</a>', unsafe_allow_html=True)

if __name__ == '__main__':
    main()
