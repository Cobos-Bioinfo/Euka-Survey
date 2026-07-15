# Architecture

EukaSurvey has two halves that don't talk to each other at runtime:

1. **The web app** (`app.py` + `src/`) — reads a prebuilt, read-only
   `eukaryotes.db`. This is what users hit.
2. **The offline pipeline** (`db_builder/`) — fetches data from NCBI,
   Annotrieve, and ENA, and produces `eukaryotes.db`. Run manually or
   by the weekly GitHub Action. See [PIPELINE.md](PIPELINE.md).

This document covers the web-app half. For the pipeline, see
[PIPELINE.md](PIPELINE.md).

---

## Repository layout

```
.
├── app.py                   # Thin controller — wires the ui/ sections together
├── ui/                      # View layer — one render_* function per page section
│   ├── state.py             #   RootChoice (sidebar) + QueryState (results)
│   ├── query_config.py      #   Sidebar root-taxon picker → RootChoice
│   ├── sidebar.py           #   Help & Resources + project / data-source links
│   ├── summary.py           #   Genomic Resource Summary cards + Wikipedia "About" card
│   ├── tree.py              #   Explore Results: rank + form + 🌳 Tree / 📊 Table tabs
│   └── export.py            #   Export Data: explanation + TSV preview + download
├── src/                     # Web-app domain logic (no Streamlit widgets)
│   ├── constants.py         #   Shared constants (taxids, ranks, limits, schema version)
│   ├── metrics.py           #   Metric config table + CladeMetadata dataclass
│   ├── database.py          #   SQL layer over the precomputed tables
│   ├── cache.py             #   All @st.cache_* wrappers (DB conn + query/render caches)
│   ├── taxonomy.py          #   Live ETE3 fallback + valid-rank & lineage-breadcrumb lookups
│   ├── ete_utils.py         #   get_ncbi() accessor, taxid → name/rank, descendant CTE
│   ├── visualization.py     #   ETE3 tree rendering + per-leaf divergent bar charts
│   ├── wikipedia.py         #   Cached Wikipedia summary for the root-taxon "About" card
│   └── utils.py             #   DB download + schema-version check + TSV export
├── db_builder/              # Offline pipeline (see docs/PIPELINE.md)
├── tests/                   # pytest suite (uv run pytest)
├── .streamlit/              # Streamlit theme config (brand-colored light theme)
├── pyproject.toml, uv.lock  # Dependencies, managed with uv (see README "Quick start")
├── packages.txt             # apt packages for Streamlit Cloud (Qt5 trixie t64 libs)
└── eukaryotes.db            # The data — NOT in git, downloaded on first run
```

---

## UI layer (`ui/`)

`app.py` is a thin controller: it boots the DB, then calls one `render_*`
function per page section. Sections never call each other — all cross-section
state flows through two small frozen dataclasses in `ui/state.py`:

- **`RootChoice`** — produced by the **sidebar** (`render_root_control`): the
  single global "which clade?" question (root taxid + resolved name/rank).
  Drives the summary, which rolls up the whole clade regardless of rank.
- **`QueryState`** — produced by **Explore Results** (`render_results`), which
  owns the breakdown rank. Carries the root fields too, so the tree / table /
  export consumers share one object.

Page order (top to bottom): sidebar **root picker + Help**, then in the main
area the **Genomic Resource Summary** (`summary.py` — species count, Wikipedia
`About` card, four resource cards), **Explore Results** (`tree.py` — a prominent
segmented rank control + a compact filter/sort/limit form → 🌳 Tree / 📊 Table
tabs), and **Export Data** (`export.py` — the full-breakdown TSV with a preview).

---

## Database schema

`eukaryotes.db` is a single SQLite file with three tables.

### `taxid_features`

Raw per-species counts (one row per species-rank taxid).

| column             | type    | notes                                  |
|--------------------|---------|----------------------------------------|
| `taxid`            | INTEGER | PK                                     |
| `short_read_count` | INTEGER | RNA-Seq runs on Illumina/etc.          |
| `long_read_count`  | INTEGER | RNA-Seq runs on ONT / PacBio SMRT      |
| `assembly_count`   | INTEGER | Genome assemblies                      |
| `annotation_count` | INTEGER | Functional annotations                 |

The web app does not query this table directly — it reads the
precomputed aggregations below.

### `precomputed_clade_features`

One row per taxid **at any rank** (not just species). Rolled up across
the entire subtree under each taxid.

| column   | type    | notes                                                       |
|----------|---------|-------------------------------------------------------------|
| `taxid`  | INTEGER | PK                                                          |
| `n_rows` | INTEGER | Species *count* in this subtree                             |
| `c_ass`  | INTEGER | Species *covered* — i.e. with ≥1 assembly                   |
| `c_ann`  | INTEGER | Species with ≥1 annotation                                  |
| `c_rna`  | INTEGER | Species with ≥1 RNA-Seq run (any kind)                      |
| `c_lng`  | INTEGER | Species with ≥1 long-read RNA-Seq run                       |
| `s_ass`  | INTEGER | Total assembly *count* across the subtree                   |
| `s_ann`  | INTEGER | Total annotations across the subtree                        |
| `s_rna`  | INTEGER | Total RNA-Seq runs (any kind) across the subtree            |
| `s_lng`  | INTEGER | Total long-read RNA-Seq runs across the subtree             |

The convention `c_*` = "covered species" / `s_*` = "summed runs" / `p_*`
= "percentage" runs through the codebase (the percentage is computed in
Python — it isn't stored).

### `precomputed_taxa`

Caches `(root_taxid, target_rank) → list of (taxid, name)` for the six
**common root clades** × six allowed ranks. Lets the UI skip live ETE3
traversal for the common cases.

| column        | type    |
|---------------|---------|
| `root_taxid`  | INTEGER |
| `target_rank` | TEXT    |
| `taxid`       | INTEGER |
| `name`        | TEXT    |

A covering index on `(root_taxid, target_rank, taxid, name)` lets the
hot read be served from the index alone.

**Common roots** baked in: Eukaryota (2759), Animals (33208), Mammalia
(40674), Primates (9443), Fungi (4751), Plants (33090) — see
`src/constants.py::COMMON_CLADES`. **Allowed ranks**: phylum, class,
order, family, genus, species.

For any other root/rank combination, the app falls back to a live ETE3
descendant traversal via `src.taxonomy.get_taxa_at_rank`.

---

## Query flow

```
User picks root_taxid + target_rank
        │
        ▼
get_taxa_count_cached(conn, root_taxid, target_rank)
        │                                       (precomputed_taxa hit?)
        ├── yes → is_precomputed = True
        │
        └── no  → fetch_taxa_cached  ── live ETE3 traversal
                                          (taxonomy.get_taxa_at_rank)
        ▼
User clicks "Generate Tree & Table"
        │
        ├── if precomputed:
        │     database.get_filtered_taxa_metadata (SQL: WHERE + ORDER + LIMIT)
        │
        └── else:
              get_phylum_metadata_cached (bulk fetch)
              + database.filter_sort_limit_metadata (same logic, in Python)
              # Both paths share _row_to_metadata + the FilterLogic enum, so
              # they can't drift — parity covered by tests/test_filters_parity.py
        ▼
the resulting metadata feeds two synced views (st.tabs):
   ├── 🌳 Tree  → visualization.render_tree_in_process (SPAWNED subprocess,
   │             see below) → SVG → tempfile → st.image + SVG download
   └── 📊 Table → st.dataframe (coverage ProgressColumns) + per-view TSV download
```

For TSV export, the flow is simpler:

```
utils.generate_tsv → database.build_phylum_metadata → csv.writer → TSV
```

TSV export does **not** apply filter/sort/limit — it always exports the
full breakdown.

---

## Streamlit caching

All of these wrappers live in **`src/cache.py`** (imported by `app.py` and the
`ui/` sections); `utils.generate_tsv` and `wikipedia.get_taxon_summary` carry
their own `@st.cache_data` in their own modules.

| Function                              | Decorator                    | Keyed on                                                                |
|---------------------------------------|------------------------------|-------------------------------------------------------------------------|
| `get_db_ready`                        | `@st.cache_resource`         | (one-time)                                                              |
| `get_db_connection`                   | `@st.cache_resource`         | (one-time read-only conn)                                               |
| `get_taxa_count_cached`               | `@st.cache_data`             | `root_taxid, target_rank`                                               |
| `fetch_taxa_cached`                   | `@st.cache_data`             | `root_taxid, target_rank`                                               |
| `get_phylum_metadata_cached`          | `@st.cache_data`             | `tuple(taxids), exclude_empty`                                          |
| `get_filtered_taxa_metadata_cached`   | `@st.cache_data`             | `root_taxid, target_rank, exclude_empty, filter keys, logic, sort, top` |
| `generate_tree_svg_cached`            | `@st.cache_data`             | `phylum_metadata, include_counts`                                       |
| `utils.generate_tsv`                  | `@st.cache_data`             | `root_taxid, target_rank, fetch_func`                                   |

Taxid lists passed to cached functions are passed as **tuples**, since
Streamlit's data cache requires hashable args.

---

## Why tree rendering happens in a subprocess

ETE3 calls into PyQt5 to render trees. PyQt5 requires its `QApplication`
to be created on a process's *main thread*. Streamlit, however, runs
user callbacks on worker threads. The workaround in
`src/cache.py::generate_tree_svg_cached`:

1. `multiprocessing.get_context('spawn').Process(...)` launches a fresh
   process (the main thread of that process becomes Qt's main thread).
2. The child runs `visualization.render_tree_in_process`, which builds the
   ETE3 topology and writes the rendered SVG to the path handed in. It uses
   Qt's built-in **`offscreen` platform plugin** (`QT_QPA_PLATFORM=offscreen`,
   pinned at `visualization.py` import time) — so there is **no Xvfb /
   pyvirtualdisplay** dependency anywhere (local, CI, or Cloud); only the Qt5
   system libs in `packages.txt` are needed.
3. The parent waits with a **timeout** (`p.join(timeout=120)`). On
   timeout the child is `terminate()`d → `kill()`d.
4. The SVG bytes are read back from the file, the file is removed in a
   `try/finally`.

A second tempfile is needed for *display* because `st.image` chokes on
raw SVG bytes (PIL doesn't recognize the format), so the bytes are
written back to disk and `st.image` is handed the path (`ui/tree.py`).

---

## ETE3 NCBITaxa: the thread-affinity caveat

`NCBITaxa` opens a SQLite connection to the local NCBI taxonomy
database, and SQLite connections are *not* safe to share across threads
by default. Streamlit runs callbacks on worker threads, so
`src/ete_utils.py::get_ncbi()` hands out a **`threading.local()`-cached**
instance — one `NCBITaxa` per worker thread for the process lifetime,
which sidesteps the `check_same_thread` issue without re-opening the
taxonomy DB on every call. All production call sites go through it.

Taxid → name / rank lookups additionally carry `@functools.lru_cache`,
so each unique taxid resolves at most once per process.

---

## Status & further reading

The large architectural refactor catalogued in
[REFACTORING_AUDIT.md](../REFACTORING_AUDIT.md) is essentially complete — the
`ui/` split, the unified filter/sort/limit path, the `get_ncbi()` thread-local
accessor, the `tests/` suite, `PRAGMA user_version` schema versioning, and the
staged `db_builder` pipeline have all landed (only a few Low-priority items
remain; see the audit's status column).

Ongoing UI/UX work — layout, theming, the in-app table, the Wikipedia card,
etc. — is tracked in [UI_IMPROVEMENT_PLAN.md](../UI_IMPROVEMENT_PLAN.md).
