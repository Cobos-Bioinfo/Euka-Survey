"""Sidebar: help + project links + database version. No app state."""

import streamlit as st

from src import db_version

_GUIDE = """
**What is this?**  
EukaSurvey shows how much public genomic data exists for any branch of the
eukaryotic tree of life. Pick a clade and it tells you — overall and broken
down by taxonomic rank — how many of its species have each of four resources:

- **Assemblies** — genome assemblies _(source: NCBI)_
- **Annotations** — functional gene annotations _(source: Annotrieve)_
- **RNA-Seq** — any RNA-Seq runs _(source: ENA)_
- **Long-Read RNA-Seq** — RNA-Seq on Oxford Nanopore / PacBio _(source: ENA)_

---

**1 · Choose a clade** &nbsp;_(sidebar, top)_  
Pick a **Root taxon** — one of the common clades or any NCBI Taxon ID.
Everything on the page describes this clade and the species inside it.

**2 · Read the Summary**  
*Genomic Resource Summary* shows the clade's **total species**, a short
Wikipedia blurb, and four cards — one per resource — each with the **species
covered** (how many have at least one), the **% of species covered**, and the
**total count** of records.

**3 · Break it down & explore**  
In *Explore Results*, choose a **rank** (phylum → species) to split the clade
into groups; each group becomes one row. Optionally refine it:
- **Require data for** — keep only groups that have a resource (combine several
  with **Match ALL / ANY**).
- **Sort by** + **Max taxa** — order the groups and cap how many are shown.

Then click **Generate Tree & Table**:
- **🌳 Tree** — a phylogenetic tree with a coverage bar per group _(download as SVG)_.
- **📊 Table** — the same groups as a sortable table _(download as TSV)_.

**4 · Export**  
*Export Data* downloads the **complete** breakdown — every taxon, never
filtered or limited — as a TSV, with a preview of the first rows.

---

**Reading the numbers**
- **Species** = unique species in that clade/group.
- **Covered** = species with ≥1 of a resource; **Total** = sum of all records
  (a species can have many).
- The divergent bars show the **% of species covered**: assemblies &
  annotations in **blue** (left), RNA-Seq & long-read in **green** (right).

**About the data**
Counts are precomputed weekly from NCBI, Annotrieve, and ENA. A species may
have data for some resources but not others — that's exactly what this tool
helps you spot.
"""


def render_sidebar(db_tag: str | None = None) -> None:
    with st.sidebar:
        st.divider()
        st.header("Help & Resources")

        with st.expander("How to use EukaSurvey", expanded=True):
            st.markdown(_GUIDE)

        st.subheader("Project & sources", anchor=False)
        st.markdown(
            "- [EukaSurvey on GitHub](https://github.com/Cobos-Bioinfo/Euka-Survey) :material/open_in_new:\n"
            "- [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/) — assemblies :material/open_in_new:\n"
            "- [Annotrieve](https://genome.crg.es/annotrieve/) — annotations :material/open_in_new:\n"
            "- [ENA](https://www.ebi.ac.uk/ena/browser/) — RNA-Seq :material/open_in_new:"
        )

        _render_db_version(db_tag)


def _render_db_version(db_tag: str | None) -> None:
    """Compact footer showing when the *served* database was built, derived
    from its release tag (the one `get_db_ready` recorded). A user-provided DB
    with no recorded version (`db_tag` is None) shows a neutral 'local build'
    note instead of a date."""
    st.divider()
    date = db_version.date_from_tag(db_tag)
    if date and db_tag:
        st.caption(
            f":material/database: **Database** · built {date}  \n"
            f"[`{db_tag}`]({db_version.release_url(db_tag)}) :material/open_in_new:"
        )
    else:
        st.caption(":material/database: **Database** · local build")
