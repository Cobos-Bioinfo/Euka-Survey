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
   git clone https://github.com/Cobos-Bioinfo/euka_survey.git
   cd euka_survey
   ```
2. **Install Python dependencies:**
   Use the provided environment.yml file to create a conda environment (This guarantees C-dependencies like ETE3 and PyQt5 work properly):
   ```bash
   conda env create -f environment.yml
   conda activate euka_survey
   ```
3. **Launch the web application:**
   ```bash
   streamlit run app.py
   ```
   *Note: If the `eukaryote_taxid_features_*.db` file isn't found locally, the app will automatically attempt to download the precomputed copy from Zenodo into the root folder.*

## Cloud Deployment (Streamlit Community Cloud)

This project is perfectly formatted for 1-click deployment on Streamlit Community Cloud.
Because of the heavy dependency on `ete3` and `PyQt5` for rendering SVG phylogenetic charts, Streamlit Cloud detects the `environment.yml` and natively provisions the correct conda backing.

Similarly, the app will automatically download the SQLite database from a Zenodo DOI bucket to boot, making the GitHub repo 100% code-driven without storing large binaries.

## Offline DB Generation Pipeline
If you ever want to update the raw organism features by fetching fresh NCBI/ENA/Annotrieve data:
```bash
python db_builder/pipeline_build_db.py
```
This pipeline will query the web, build the `taxid_features` table across all ~1.8M eukaryotic species, patch missing zero-count taxonomic entries, and natively generate the roll-up math in the `precomputed_clade_features` table, dropping a completely finalized `db` ready for `app.py` utilization.

## Notes
- **Exclusion of Human/Mouse data**: RNA-seq runs for humans (taxID 9606) and mice (taxID 10090) are explicitly hardcoded to be excluded from ENA queries. This is an intentional project design to avoid significant API bloat for these highly sequenced model organisms.
- Multi-processing limitation patches have been successfully implemented to bypass SQLite check-thread locks and PyQt5 MainThread constraints within Streamlit's architecture.
