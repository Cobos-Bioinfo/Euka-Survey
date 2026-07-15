"""EukaSurvey Streamlit app — thin controller.

The page is composed of five independent sections, each rendered by
its own `ui/` module. The cache wrappers and DB constants live in
`src/cache.py` and `src/constants.py` respectively.
"""

import streamlit as st

from src.cache import get_db_connection, get_db_ready
from ui.export import render_export
from ui.query_config import render_root_control
from ui.sidebar import render_sidebar
from ui.summary import render_summary
from ui.tree import render_results

st.set_page_config(
    page_title="EukaSurvey Platform",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("🧬 EukaSurvey", anchor=False)
    st.subheader("The Genomic Resource Explorer for Eukaryotes", divider="blue", anchor=False)
    st.caption("Visualize genomic data availability across the Eukaryotic Tree of Life.")

    try:
        db_tag = get_db_ready()
    except RuntimeError:
        st.error("Could not download the database. Please refresh the page to try again.")
        st.stop()

    # Keyed on the DB's release tag so a weekly hot-swap opens a fresh
    # connection to the new file (see get_db_ready / get_db_connection).
    conn = get_db_connection(db_tag)

    # Sidebar = persistent control panel: root taxon (the one global control)
    # first, help below. The breakdown rank now lives with the results.
    root = render_root_control(conn)
    render_sidebar(db_tag)

    if not root.is_valid_root:
        if root.root_taxid is not None:
            # User typed a taxid that doesn't resolve in NCBI's taxonomy.
            st.error(f"TaxID {root.root_taxid} does not exist in the NCBI taxonomy database.")
        return

    render_summary(conn, root)

    st.space("xsmall")
    query = render_results(conn, root)

    if query.has_results and query.target_rank:
        st.space("xsmall")
        render_export(conn, query)


if __name__ == "__main__":
    main()
