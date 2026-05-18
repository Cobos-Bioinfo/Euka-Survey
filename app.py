import streamlit as st
import sqlite3
import os
import multiprocessing as mp
from ete3 import NCBITaxa

# Import local modules securely
from src import taxonomy
from src import visualization
from src import database
from src import utils
from src import ete_utils

# Constants
DB_PATH = "eukaryotes.db" # For local development
# Fetch from the automatic GitHub Release action
DB_DOWNLOAD_URL = "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/latest/download/eukaryotes.db"  

# --- Streamlit Community Cloud App Name ---
st.set_page_config(page_title="EukaSurvey Platform", page_icon="🧬", layout="wide", initial_sidebar_state="expanded")

@st.cache_resource(show_spinner="Downloading Database (this happens once)...")
def get_db_ready():
    """Ensure the SQLite DB exists and is ready."""
    if utils.ensure_database(DB_PATH, DB_DOWNLOAD_URL):
        return True
    raise RuntimeError("Database download failed. Restart the app to retry.")

@st.cache_resource
def get_db_connection():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)

@st.cache_resource
def get_ncbi():
    # ETE3 uses SQLite internally. To allow cross-thread access, 
    # we initialize it without caching and instead use a thread-local approach
    # or recreate it as needed if threading issues persist.
    # However, st.cache_resource for NCBITaxa is often the cause of sqlite3.ProgrammingError.
    return NCBITaxa()

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
        
    return taxonomy.get_taxa_at_rank(root_taxid, target_rank)

# --------------------- Main App Logic --------------------- #
def main():
    # --- Main UI Layout ---
    st.title("EukaSurvey")
    st.subheader("The Genomic Resource Explorer for Eukaryotes", divider="blue")
    st.markdown("Visualize genomic data availability across the Eukaryotic Tree of Life.")

    # 1. Initialize dependencies
    try:
        get_db_ready()
    except RuntimeError:
        st.error("Could not download the database. Please refresh the page to try again.")
        st.stop()
            
    conn = get_db_connection()

    # 2. Sidebar Configuration 
    with st.sidebar:
        st.header("Help & Resources")
        
        with st.expander("How to use EukaSurvey", expanded=False):
            st.markdown("""
            **1. Define your Query**  
            Select a **Root Taxon ID** (e.g. Mammals' 40674) and a **Breakdown Rank** (e.g. Family) to slice the tree.
            
            **2. Review Summary**  
            The dashboard shows total counts for Assemblies, Annotations, and RNA-Seq across your query.
            
            **3. Filter & Sort**  
            In the *Tree Visualization* section, use **Filter Nodes** to skip taxa missing specific resources. You can combine filters with **AND/OR** logic.
            
            **4. Generate & Export**  
            Click **Generate Visualization** to view the tree. Use the **Data Export** buttons to download your query as a TSV or the tree as an SVG.
            """)

        st.subheader("Project", anchor=False)
        st.markdown("[View on GitHub](https://github.com/Cobos-Bioinfo/Euka-Survey) :material/open_in_new:")


    # 3. Query Configuration
    with st.container(border=True):
        st.subheader("Query Configuration") #, icon=":material/settings:"
        
        # Root taxon selection with common clades for convenience
        common_taxa = ["Eukaryota (2759)", "Animals (33208)", "Mammalia (40674)", "Primates (9443)", "Fungi (4751)", "Plants (33090)"]

        q_cols = st.columns([1.5, 1, 1], gap="large")
        
        with q_cols[0]:
            choice = st.selectbox(
                "Root Taxon (NCBI ID or Common Clades):", 
                ["Enter your own"] + common_taxa,
                index=1,
                placeholder="Choose a valid NCBI Taxon ID",
                key="root_taxon_selection"
            )

            # Handle the Root Taxon ID selection
            if choice == "Enter your own":
                root_taxid_input = st.text_input("Enter NCBI Taxon ID:", value="2759", placeholder="e.g. 2759 for Eukaryota")
                if root_taxid_input and str(root_taxid_input).strip().isdigit():
                    root_taxid = int(str(root_taxid_input).strip())
                else:
                    if root_taxid_input:
                        st.warning("Please enter a valid numeric Taxon ID.")
                    root_taxid = None
            else:
                taxid_map = {
                    "Eukaryota (2759)": 2759, 
                    "Animals (33208)": 33208, 
                    "Mammalia (40674)": 40674, 
                    "Primates (9443)": 9443, 
                    "Fungi (4751)": 4751, 
                    "Plants (33090)": 33090
                }
                root_taxid = taxid_map[choice]

        # Dynamic target rank Breakdown selection based on selected root taxon
        FULL_RANKS = ['domain', 'superkingdom', 'kingdom', 'superphylum', 'phylum', 'subphylum', 'superclass', 'class', 'subclass', 'superorder', 'order', 'suborder', 'superfamily', 'family', 'subfamily', 'genus', 'subgenus', 'species']
        ALLOWED_RANKS = ["phylum", "class", "order", "family", "genus", "species"]
        
        valid_options = ALLOWED_RANKS
        if root_taxid:
            try:
                # Instantiate a fresh NCBITaxa to avoid Streamlit/SQLite cross-thread connection errors
                from ete3 import NCBITaxa
                local_ncbi = NCBITaxa()
                ranks = local_ncbi.get_rank([root_taxid])
                root_rank = ranks.get(root_taxid, "no rank")
                
                if root_rank not in FULL_RANKS:
                    # Find effective rank via lineage if 'no rank' or non-canonical
                    lineage = local_ncbi.get_lineage(root_taxid)
                    lin_ranks = local_ncbi.get_rank(lineage)
                    for anc_taxid in reversed(lineage):
                        r = lin_ranks.get(anc_taxid, "no rank")
                        if r in FULL_RANKS:
                            root_rank = r
                            break
                            
                if root_rank in FULL_RANKS:
                    root_idx = FULL_RANKS.index(root_rank)
                    valid_options = [r for r in ALLOWED_RANKS if FULL_RANKS.index(r) > root_idx]
            except ValueError:
                st.error("The selected TaxID could not be found. Please enter a valid TaxID or select from the common clades.")
                root_taxid = None

        if "rank_selection" not in st.session_state:
            st.session_state.rank_selection = valid_options[0] if valid_options else "phylum"

        with q_cols[1]:
            if valid_options:
                # Edge case: If previous selected rank was higher/equal (now invalid)
                # automatically change to highest level available rank.
                if st.session_state.rank_selection not in valid_options:
                    st.session_state.rank_selection = valid_options[0]
                    
                target_rank = st.selectbox(
                    "Breakdown by Rank:", 
                    valid_options, 
                    placeholder=None,
                    key="rank_selection"
                )
            else:
                # Edge case: Selected root taxon is species or lower
                st.warning("Selected root taxon is at the species level or lower. No further breakdown available.")
                target_rank = None

        root_name = ete_utils.get_name_from_taxid(root_taxid) if root_taxid else "Error" # type: ignore
        root_rank = ete_utils.get_rank_from_taxid(root_taxid) if root_taxid else "clade" # type: ignore

        # Provide reactive feedback on tree size
        query_taxids = []
        query_taxa = None
        num_nodes = 0
        with q_cols[2]:
            st.write("") # small alignment spacing
            if root_taxid and target_rank and root_name != "Unknown":
                try:
                    query_taxa = fetch_taxa_cached(conn, root_taxid, target_rank)
                    if query_taxa:
                        query_taxids = [t[0] for t in query_taxa]
                        num_nodes = len(query_taxids)
                        st.info(f"Tree size: **{num_nodes}** {target_rank} nodes", icon="🌲")
                        if num_nodes > 100:
                            st.caption("High node counts may take longer to compute and render.")
                    else:
                        st.warning(f"No {target_rank}s found under TaxID {root_taxid}.")
                except ValueError:
                    st.error("Invalid TaxID: Not found in database.")

    # --- Root Taxon Stat Summary --- #
    if root_taxid and root_name != "Unknown":
        st.header(f"Genomic Resource Summary: {root_name}")
        st.markdown(f"Overview of available resources across the entire _{root_name}_ {root_rank} (TaxID {root_taxid}).")
        
        # Fetch root stats dynamically
        root_metadata = database.build_phylum_metadata(conn, [root_taxid], exclude_empty=False)
        if root_metadata and root_taxid in root_metadata:
            stats = root_metadata[root_taxid]
            
            # Prominent top-level metric for Total Species
            st.metric(
                label=":material/groups: Total Species in Clade", 
                value=f"{int(stats['n_rows']):,}",
                help="Total number of unique species tracked in this clade"
            )
            
            # Balanced 4-column layout for detailed resource breakdowns
            cols = st.columns(4)
            
            # Assemblies Card
            with cols[0]:
                with st.container(border=True):
                    st.markdown("##### :material/database: :blue[Assemblies]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_ass']):,}",
                        help="Unique species with at least one genome assembly"
                    )
                    st.metric(
                        label="Total Assemblies", 
                        value=f"{int(stats['s_ass']):,}",
                        help="Total number of genome assemblies across all species"
                    )
                    
            # Annotations Card
            with cols[1]:
                with st.container(border=True):
                    st.markdown("##### :material/description: :orange[Annotations]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_ann']):,}",
                        help="Unique species with at least one functional annotation"
                    )
                    st.metric(
                        label="Total Annotations", 
                        value=f"{int(stats['s_ann']):,}",
                        help="Total number of annotated genomes across all species"
                    )
                    
            # RNA-Seq Card
            with cols[2]:
                with st.container(border=True):
                    st.markdown("##### :material/segment: :green[RNA-Seq (Any)]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_rna']):,}",
                        help="Unique species with any RNA-Seq read data"
                    )
                    st.metric(
                        label="Total Runs", 
                        value=f"{int(stats['s_rna']):,}",
                        help="Total number of RNA-Seq runs across all species"
                    )
                    
            # Long-Read RNA Card
            with cols[3]:
                with st.container(border=True):
                    st.markdown("##### :material/reorder: :green[Long-Read RNA-Seq]", help="RNA-Seq experiments performed with Oxford Nanopore or PacBio SMRT platforms")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_lng']):,}",
                        help="Unique species with at least one long-read RNA-Seq experiment"
                    )
                    st.metric(
                        label="Total Runs", 
                        value=f"{int(stats['s_lng']):,}",
                        help="Total number of Long-Read RNA-Seq runs across all species"
                    )
        else:
            st.warning("No data found for this Root Taxon.")
            
        # st.divider()
    elif root_taxid and root_name == "Unknown":
        st.error(f"TaxID {root_taxid} does not exist in the NCBI taxonomy database.")

    # --- Open Query-Specific Database Buttons --- #
    if root_taxid and root_name != "Unknown":
        st.header("Explore Primary Databases")
    
        with st.container(horizontal=True, gap="medium"):
            cols = st.columns(3, gap="medium", width="stretch", border=True)
            
            with cols[0]:
                st.subheader("ENA Browser", text_alignment="center")
                ena_url = f"https://www.ebi.ac.uk/ena/browser/advanced-search?result=read_run&query=tax_tree({root_taxid})%20AND%20library_strategy%3D%22rna-seq%22&fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy&limit=0"
                st.markdown(f'<a href="{ena_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #18974c; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open RNA-Seq Reads for {root_name}</a>', unsafe_allow_html=True)
    
            with cols[1]:
                st.subheader("NCBI Datasets", text_alignment="center")
                ncbi_url = f"https://www.ncbi.nlm.nih.gov/datasets/genome/?taxon={root_taxid}"
                st.markdown(f'<a href="{ncbi_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #20558a; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open Genome Assemblies for {root_name}</a>', unsafe_allow_html=True)
    
            with cols[2]:
                st.subheader("Annotrieve", text_alignment="center")
                anno_url = f"https://genome.crg.es/annotrieve/annotations/details/?taxon={root_taxid}"
                st.markdown(f'<a href="{anno_url}" target="_blank" style="display: block; width: 100%; text-align: center; background-color: #f07900; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">Open Annotations for {root_name}</a>', unsafe_allow_html=True)
        # st.divider()

    st.space("xsmall")
    # --- Tree Visualization Settings & Generation --- #
    if root_taxid and root_name != "Unknown" and query_taxids:
        st.header("Tree Visualization")
        
        with st.container(border=True):
            st.subheader("Filter Nodes")
            filter_options = {
                "Assemblies": "c_ass",
                "Annotations": "c_ann",
                "RNA-Seq (Any)": "c_rna",
                "Long-Read RNA": "c_lng"
            }
            selected_filters = st.multiselect("Require data for (leaves node out if it lacks data):", list(filter_options.keys()), placeholder="Select features...")
            
            filter_logic = "Match ALL (AND)"
            if len(selected_filters) > 1:
                filter_logic = st.segmented_control("Condition", ["Match ALL (AND)", "Match ANY (OR)"], default="Match ALL (AND)")
            
            st.subheader("Sorting & Limits")
            sort_options = {
                "Species": "n_rows",
                "Assemblies": "c_ass",
                "Annotations": "c_ann",
                "RNA-Seq (Any)": "c_rna",
                "Long-Read RNA": "c_lng"
            }
            cols = st.columns(2)
            
            with cols[0]:
                sort_by_label = st.selectbox("Sort top nodes by number of: ", list(sort_options.keys()), key="sort_by_selection")
                sort_by_key = sort_options[sort_by_label]
                
                exclude_empty = st.toggle("Exclude Empty Taxa (Zero data across all fields)", value=True)

            with cols[1]:
                # Dynamic node limit options based on availability and hard cap
                HARD_CAP = 500
                effective_max = min(num_nodes, HARD_CAP)
                
                # Filter down the breakpoints to only show those valid for the current tree size
                standard_breakpoints = [10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500]
                valid_options_limit = [str(b) for b in standard_breakpoints if b < effective_max]
                
                # Add dynamic "All" and "Custom"
                valid_options_limit.append(f"All ({effective_max})")
                valid_options_limit.append("Custom")
                
                # Determine smart default index
                if "50" in valid_options_limit:
                    default_idx = valid_options_limit.index("50")
                else:
                    # If 50 is too high, pick the last numeric option before "All" (which is the effective max) or All.
                    default_idx = max(0, len(valid_options_limit) - 2)
                
                selected_limit = st.selectbox("Max nodes to display", valid_options_limit, index=default_idx, key="limit_selection", help=f"Hard cap set to {HARD_CAP} nodes for performance.")
                
                if selected_limit == "Custom":
                    top_n = st.number_input("Enter custom max nodes", min_value=2, max_value=effective_max, value=min(50, effective_max), step=1)
                elif selected_limit.startswith("All"):
                    top_n = effective_max
                else:
                    top_n = int(selected_limit)

                include_counts = st.toggle("Show Numeric Details in Tree", value=True, help="Toggle display of per-feature resource counts in the tree visualization.")

        # 3. Generate Visualization on button click
        if st.button("Generate Visualization", type="primary", icon=":material/account_tree:"):
            if not target_rank:
                st.error("Cannot generate tree: Root taxon is at species level or lower, no further taxonomic breakdown is possible.")
                st.stop()
            if not query_taxids:
                st.error(f"Cannot generate tree. No {target_rank}s found or invalid TaxID {root_taxid}.")
                st.stop()
                
            with st.spinner(f"Aggregating data and filtering clades..."):
                
                # Fetch data for all found taxids
                phylum_metadata = database.build_phylum_metadata(conn, query_taxids, exclude_empty)
                
                # Apply multi-select filtering
                if selected_filters and phylum_metadata:
                    filtered_metadata = {}
                    filter_keys = [filter_options[f] for f in selected_filters]
                    
                    for taxid, stats in phylum_metadata.items():
                        if filter_logic == "Match ALL (AND)":
                            if all(stats.get(k, 0) > 0 for k in filter_keys):
                                filtered_metadata[taxid] = stats
                        else:  # Match ANY (OR)
                            if any(stats.get(k, 0) > 0 for k in filter_keys):
                                filtered_metadata[taxid] = stats
                    phylum_metadata = filtered_metadata
                
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
                # Build and render ETE3 tree map using a Subprocess to respect PyQt threading rules
                tmp_svg = "temp_tree_render.svg"
                if os.path.exists(tmp_svg):
                    os.remove(tmp_svg)
                    
                ctx = mp.get_context('spawn')
                p = ctx.Process(target=visualization.render_tree_in_process, args=(phylum_metadata, include_counts, tmp_svg))
                p.start()
                p.join()
                
                if p.exitcode != 0 or not os.path.exists(tmp_svg):
                    st.error("Failed to render the tree. This is usually due to Qt/X11 rendering restrictions.")
                    st.stop()
                
                st.image(tmp_svg, use_container_width=True)
                
                # Export button
                with open(tmp_svg, "rb") as f:
                    st.download_button(
                        label="Download SVG Figure",
                        data=f.read(),
                        file_name=f"tree_{root_taxid}_{target_rank}.svg",
                        mime="image/svg+xml",
                        icon=":material/download:",
                        type="primary"
                    )
                
                # Store success in session state to persist buttons
                st.session_state.rendered_taxid = root_taxid

    st.space("xsmall")
    # --- TSV Data Export Section --- #
    if root_taxid and target_rank and query_taxa and root_name != "Unknown":
        st.header("Data Export")
        st.write("Download the complete overview of the current query as a TSV file.")
        
        # In Streamlit, data for download_button is evaluated on render. 
        # We cache the generator to maintain UI performance instead of a 2-button prepare flow.
        tsv_filename = f"{root_name.replace(' ', '_')}_{target_rank}_data.tsv"
        tsv_data = utils.generate_tsv(conn, query_taxa)
        
        st.download_button(
            label="Download TSV",
            data=tsv_data,
            file_name=tsv_filename,
            mime="text/tab-separated-values",
            icon=":material/download:",
            type="primary"
        )

if __name__ == "__main__":
    main()