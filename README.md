# Eukaryote Survey Web App

## Description
This project provides a fast Streamlit Web Application for exploring genomic sequencing data across the entire Eukaryotic tree of life. It tracks whole genome assemblies, functional annotations, and RNA-seq reads (divided into short- and long-reads) via a highly optimized SQLite database.

**Try [Euka-Survey](https://euka-survey-62bi4d34cytdpb56zmhms2.streamlit.app/) now!**

**Main Use Case:** Identifying clades, families, or species that lack specific types of sequencing data, or discovering clades rich in genomic resources for comparative studies directly in your browser.

**Target Users:** Bioinformaticians, evolutionary biologists, and comparative genomicists conducting broad taxonomic surveys or meta-analyses who need to evaluate available molecular resources instantly without manually navigating NCBI or ENA portals.

## Key Features
- **Real-time Querying**: Instant lookups by NCBI Taxon ID or common eukaryotic clades.
- **Dynamic Resource Statistics**: Metrics for whole genome assemblies, functional annotations, and RNA-seq data (short and long-reads).
- **Advanced Filtering**: Combine multiple genomic resource requirements (e.g., "Must have Assemblies AND Long-Read RNA") to identify specific gaps.
- **Phylogenetic Exploration**: Custom SVG tree rendering with breakdown by taxonomic rank (Phylum to Species).
- **Data Export**: Download query results as optimized TSV files or high-quality SVG phylogenetic charts.

## Project Architecture
- `app.py`: The main Streamlit Web App entry point.
- `src/`: Core logic for database querying, taxonomy routing, TSV generation, and ETE3 tree rendering.
- `db_builder/`: The offline pipeline for aggregating data from NCBI, ENA, and Annotrieve.

## Architecture Notes

### Thread-safe Taxonomy Lookups

ETE3's `NCBITaxa` uses SQLite internally. Python's `sqlite3` enforces a rule
that a connection created in one thread cannot be used in another — this causes
`sqlite3.ProgrammingError` in Streamlit, because `st.cache_resource` shares a
single instance across all sessions and their threads.

The fix is to scope the `NCBITaxa` instance to the user's session via
`st.session_state`, which guarantees the SQLite connection is always used in the
same thread it was created in, while still avoiding repeated re-initialization
on every UI interaction (rerun).

```python
# Safe — one connection per session, same thread always
def get_local_ncbi():
    if "ncbi" not in st.session_state:
        st.session_state.ncbi = NCBITaxa()
    return st.session_state.ncbi

# Unsafe — shared across sessions/threads → ProgrammingError
@st.cache_resource
def get_ncbi():
    return NCBITaxa()
```

## Using the Application
1. **Set Root Taxon**: Choose a starting point in the eukaryotic tree (e.g., Mammalia - TaxID 40674).
2. **Select Breakdown Rank**: Choose the taxonomic resolution (e.g., Order, Family, or Genus).
3. **Configure Filters**: In the "Tree Visualization" section, use the multi-select filter to require specific data types. Use the **Match ALL/ANY** toggle to switch between strict and broad filtering.
4. **Sort and Limit**: Rank the results by your metric of interest and set a display limit (up to 500 nodes).
5. **Analyze & Export**: Generate the tree to visualize coverage or download the TSV for downstream analysis.

## Installation & Local Execution

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Cobos-Bioinfo/Euka-Survey.git
   cd Euka-Survey
   ```
2. **Install Python dependencies:**
   Use the provided environment.yml file to create a conda environment (This guarantees C-dependencies like ETE3 and PyQt5 work properly):
   ```bash
   conda env create -f environment.yml
   conda activate euka_refactored
   ```
3. **Launch the web application:**
   ```bash
   streamlit run app.py
   ```
   *Note: If the `eukaryotes.db` file isn't found locally, the app will automatically attempt to download the precomputed copy from GitHub Releases into the root folder.*

## Cloud Deployment (Streamlit Community Cloud)

This project is formatted for 1-click deployment on Streamlit Community Cloud.
Because of the heavy dependency on `ete3` and `PyQt5` for rendering SVG phylogenetic charts, Streamlit Cloud detects the `environment.yml` and natively provisions the correct conda backing.

Similarly, the app will automatically download the SQLite database from the GitHub Releases into the root folder to boot.

## Offline DB Generation Pipeline
If you ever want to update the raw organism features by fetching fresh NCBI/ENA/Annotrieve data:
```bash
python db_builder/pipeline_build_db.py
```
This pipeline will query the web, build the `taxid_features` table across all ~1.8M eukaryotic species, patch missing zero-count taxonomic entries, and natively generate the roll-up math in the `precomputed_clade_features` table.

For instantaneous UI preview responsiveness for commonly searched clades without blocking the main thread, run the taxa cache generator:
```bash
python db_builder/precompute_taxa.py --db eukaryotes.db
```
This script bakes the rank breakdown node mappings into the `precomputed_taxa` table, dropping a completely finalized `db` ready for `app.py` utilization.

## Contributing
Contributions are welcome! Please fork the repository and submit a pull request with your changes. For major changes, please open an issue first to discuss what you would like to change.