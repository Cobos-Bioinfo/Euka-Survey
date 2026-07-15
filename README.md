# EukaSurvey

**A genomic resource explorer for the eukaryotic tree of life.**

EukaSurvey is a Streamlit web app that lets you see, at a glance, which
clades of eukaryotes have what kinds of genomic data publicly available:
genome assemblies (NCBI), functional annotations (Annotrieve), and RNA-seq
runs (ENA), split into short-read and long-read.

The data is precomputed weekly into a SQLite database
(`eukaryotes.db`, ~400 MB) that the app downloads on first launch.

**Try it now:** <https://euka-survey.streamlit.app/>

---

## Who it's for

- **Comparative genomicists** evaluating data coverage across a clade
  before designing a study.
- **Bioinformaticians** identifying data gaps (e.g. "which mammalian
  families have an assembly but no annotation?").
- **Evolutionary biologists** building reading lists or grant proposals
  around well- or under-sampled lineages.

## What you can do with it

1. **Pick a clade** — choose a **Root taxon** in the sidebar (a built-in
   clade like Mammalia, or any NCBI Taxon ID). The whole page describes
   this clade and the species inside it.
2. **See its coverage at a glance** — the *Genomic Resource Summary*
   shows the clade's total species, a short Wikipedia blurb, and four
   cards (assemblies, annotations, RNA-Seq, long-read RNA-Seq) each with
   the species covered, the % of species covered, and the total counts.
3. **Break it down** — in *Explore Results*, choose a **breakdown rank**
   (phylum → species; restricted to ranks below the root's own rank) to
   split the clade into groups, then optionally **filter** ("must have an
   assembly AND long-read RNA-Seq"), **sort** by any metric, and **limit**
   to the top N.
4. **Visualize two ways** — one click generates two synced views of the
   breakdown:
   - a **🌳 phylogenetic tree** with per-group divergent bar charts
     (downloadable as SVG), and
   - a sortable **📊 table** (downloadable as TSV).
5. **Export** — download the **complete** breakdown (every taxon,
   unfiltered) as a TSV for downstream analysis, with an in-app preview.

---

## Quick start (local)

```bash
git clone https://github.com/Cobos-Bioinfo/Euka-Survey.git
cd Euka-Survey

# uv handles Python + deps. Install once: https://docs.astral.sh/uv/
uv sync                       # creates .venv and installs the app deps
uv run streamlit run app.py
```

The app will open in your browser. On first launch it downloads
`eukaryotes.db` (~300 MB) from the latest GitHub Release. Subsequent
launches use the cached copy.

`uv` reads `pyproject.toml` + `uv.lock` for a reproducible environment.
The dev tools (pytest) are pulled in automatically; pipeline-only deps
are opt-in via `uv sync --extra pipeline`.

## Cloud deployment

The repo is configured for one-click Streamlit Community Cloud
deployment. Streamlit Cloud detects `uv.lock` (highest priority among
supported dependency formats) and installs the Python deps via uv;
`packages.txt` declares the minimal Qt5 system libraries needed for
headless tree rendering.

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the code is laid
  out, the SQLite schema, why tree rendering needs a subprocess.
- [docs/PIPELINE.md](docs/PIPELINE.md) — the offline `db_builder`
  pipeline that produces `eukaryotes.db`. Read this if you want to
  rebuild the DB or contribute to data sourcing.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — dev environment,
  conventions, in-flight refactor work.

If you're auditing or planning improvements:

- [REFACTORING_AUDIT.md](REFACTORING_AUDIT.md) — full architectural
  audit + technical-debt ranking + roadmap.
- [REFACTORING_CHANGELOG.md](REFACTORING_CHANGELOG.md) — per-item log
  of refactor work done, with rationale.
- [UI_IMPROVEMENT_PLAN.md](UI_IMPROVEMENT_PLAN.md) — the living plan for
  the web-app UI/UX: current layout inventory, themed backlog, and a
  changelog of UI work.

---

## License

See [LICENSE](LICENSE).

## Contributing

Issues and pull requests welcome. For larger changes please open an
issue first — see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the
conventions emerging from the in-flight refactor.
