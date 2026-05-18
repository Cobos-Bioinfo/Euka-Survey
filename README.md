# Eukaryote Survey Web App

## Description
This project provides a fast Streamlit Web Application for exploring genomic sequencing data across the entire Eukaryotic tree of life. It tracks whole genome assemblies, functional annotations, and RNA-seq reads (divided into short- and long-reads) via a highly optimized SQLite database.

**Try [Euka-Survey](https://euka-survey-62bi4d34cytdpb56zmhms2.streamlit.app/) now!**

**Main Use Case:** Identifying clades, families, or species that lack specific types of sequencing data, or discovering clades rich in genomic resources for comparative studies directly in your browser.

**Target Users:** Bioinformaticians, evolutionary biologists, and comparative genomicists conducting broad taxonomic surveys or meta-analyses who need to evaluate available molecular resources instantly without manually navigating NCBI or ENA portals.

## Project Architecture
- `app.py`: The main Streamlit Web App entry point. It provides a real-time querying interface using the natively precomputed metrics.
- `src/`: Contains core Python module logic for database querying, taxonomy routing, and divergent bar chart rendering.
- `db_builder/`: The offline pipeline. These scripts aggregate data from NCBI Datasets, Annotrieve, and EBI ENA, then build and precompute the optimized local SQLite database (`eukaryote_taxid_features_*.db`) allowing the web app to do `O(1)` millisecond lookups instead of runtime graph traversals.

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
   *Note: If the `eukaryotes.db` file isn't found locally, the app will automatically attempt to download the precomputed copy from Github Releases into the root folder.*

## Cloud Deployment (Streamlit Community Cloud)

This project is formatted for 1-click deployment on Streamlit Community Cloud.
Because of the heavy dependency on `ete3` and `PyQt5` for rendering SVG phylogenetic charts, Streamlit Cloud detects the `environment.yml` and natively provisions the correct conda backing.

Similarly, the app will automatically download the SQLite database from the Github Releases into the root folder to boot.

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