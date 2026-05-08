#!/usr/bin/env python3
import os
import re
import argparse
import shutil
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from ete3 import NCBITaxa, TreeStyle, TextFace, ImgFace, NodeStyle

# ── Constants ────────────────────────────────────────────────────────────────
DATA_COLS = ['short_read_count', 'long_read_count', 'assembly_count', 'annotation_count']
TMP_DIR   = ".tmp_bars"

# Paired ColorBrewer palette
C_ASS_LIGHT = "#a6cee3"   # Assemblies    (light blue)
C_ANN_DARK  = "#1f78b4"   # Annotations   (dark  blue)
C_RNA_LIGHT = "#b2df8a"   # Any RNA-Seq   (light green)
C_LNG_DARK  = "#33a02c"   # Long-Read RNA (dark  green)

# Shared bar-chart geometry
BAR_FIG_W   = 4.0         # inches  → 400 px at 100 dpi
BAR_FIG_H   = 0.2         # inches  → 55  px  (was 0.30)
BAR_DPI     = 100         # 100
BAR_HEIGHT  = 1.0         # fraction of y-axis height (0.55)
GRID_TICKS  = [25, 50, 75, 100]
GRID_COLOR  = "#d4d4d4"
SPINE_COLOR = "#555555"

# Cache for images that are rendered only once
_AXIS_IMG_PATH  = None
_LEGEND_IMG_PATH = None


# ── Data loading ──────────
def load_data(data_dir, ncbi, min_organisms, exclude_empty):
    """Load TSV files, compute counts and percentages per taxon."""
    phylum_metadata  = {}
    excluded_count   = 0

    for filename in os.listdir(data_dir):
        if not filename.endswith(".tsv"):
            continue
        match = re.search(r'^(\d+)_', filename)
        if not match:
            print(f"  Warning – skipping {filename}: no taxid prefix found.")
            continue
        
        taxid = int(match.group(1))
        filepath = os.path.join(data_dir, filename)

        try:
            df = pd.read_csv(
                filepath, sep=r'\s+', skiprows=1,
                names=['taxid'] + DATA_COLS
            )
            n = len(df)
            if n < min_organisms:
                continue

            if n > 0:
                c_ass = int((df['assembly_count']  > 0).sum())
                c_ann = int((df['annotation_count'] > 0).sum())
                c_rna = int(((df['short_read_count'] > 0) |
                              (df['long_read_count']  > 0)).sum())
                c_lng = int((df['long_read_count']   > 0).sum())

                s_ass = int(df['assembly_count'].sum())
                s_ann = int(df['annotation_count'].sum())
                s_rna = int(df['short_read_count'].sum() + df['long_read_count'].sum())
                s_lng = int(df['long_read_count'].sum())

                # Guard: annotation cannot logically exceed assembly
                # NOTE: LOOK INTO THIS
                c_ann = min(c_ann, c_ass)
                c_lng = min(c_lng, c_rna)

                p_ass = c_ass / n * 100
                p_ann = c_ann / n * 100
                p_rna = c_rna / n * 100
                p_lng = c_lng / n * 100
            else:
                c_ass = c_ann = c_rna = c_lng = 0
                s_ass = s_ann = s_rna = s_lng = 0
                p_ass = p_ann = p_rna = p_lng = 0.0

            if exclude_empty and c_ass == 0 and c_ann == 0 and c_rna == 0 and c_lng == 0:
                excluded_count += 1
                continue

            phylum_metadata[taxid] = {
                'n_rows': n,
                'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
                's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
                'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
            }

        except Exception as e:
            print(f"  Warning – skipping {filename}: {e}")

    if exclude_empty and excluded_count > 0:
        print(f"Excluded {excluded_count} empty taxa.")

    return phylum_metadata


# ── Bar chart helpers ────────────────────────────────────────────────────────
def _apply_shared_axes(ax):
    """Apply grid lines, center spine and cosmetics shared by every bar row."""
    # Subtle vertical grid at ±25 / ±50 / ±75
    for x in GRID_TICKS:
        ax.axvline( x, color=GRID_COLOR, linewidth=0.6, zorder=0)
        ax.axvline(-x, color=GRID_COLOR, linewidth=0.6, zorder=0)

    # Center spine
    ax.axvline(0, color=SPINE_COLOR, linewidth=0.6, linestyle='--', zorder=4)

    ax.set_xlim(-105, 105) # +-100
    ax.set_ylim(-0.5,  0.5)


def generate_bar_chart(taxid, meta):
    """
    Horizontal divergent bar for a single taxon.

    Left  (negative x): Assemblies (light) with Annotations overlaid (dark).
    Right (positive x): Any RNA-Seq (light) with Long-Read overlaid (dark).

    The dark bar is always ≤ the light bar (enforced in load_data), so the
    darker colour represents the *annotated / long-read fraction* of the
    lighter bar — visually a "filled subset" effect.
    """
    fig, ax = plt.subplots(figsize=(BAR_FIG_W, BAR_FIG_H), dpi=BAR_DPI)
    _apply_shared_axes(ax)

    kw = dict(height=BAR_HEIGHT, align='center',
              edgecolor='white', linewidth=0.4)

    # Left side ────────────────────────────────────────────────────────────
    ax.barh(0, -meta['p_ass'], color=C_ASS_LIGHT, zorder=2, **kw)
    ax.barh(0, -meta['p_ann'], color=C_ANN_DARK,  zorder=3, **kw)

    # Right side ───────────────────────────────────────────────────────────
    ax.barh(0, meta['p_rna'], color=C_RNA_LIGHT, zorder=2, **kw)
    ax.barh(0, meta['p_lng'], color=C_LNG_DARK,  zorder=3, **kw)

    ax.axis('off')
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    out_path = os.path.join(TMP_DIR, f"{taxid}.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    return out_path


def generate_axis_img():
    """
    Axis ruler rendered once and reused.

    Draws a full-width baseline with tick marks at 0, ±25, ±50, ±75, ±100
    and labels at 0, ±50, ±100 to keep it uncluttered.
    """
    global _AXIS_IMG_PATH
    if _AXIS_IMG_PATH is not None:
        return _AXIS_IMG_PATH

    fig, ax = plt.subplots(figsize=(BAR_FIG_W, 0.30), dpi=BAR_DPI)
    ax.set_xlim(-105, 105) # +-100, changed to 105 to avoid clipping of the outermost ticks
    ax.set_ylim(0, 1)
    ax.axis('off')

    # Baseline (drawn in data coords: y=0.95 across full x range)
    ax.plot([-100, 100], [0.95, 0.95], color=SPINE_COLOR, linewidth=0.8)

    def _tick(x, major=False):
        h  = 0.55 if major else 0.35
        # Draw tick downward from the baseline using data coordinates
        ax.plot([x, x], [0.95, 0.95 - h],
                color=SPINE_COLOR,
                linewidth=(1.0 if major else 0.6))

    labeled = {-100: "100", -50: "50", 0: "0", 50: "50", 100: "100"}
    for x in [-100, -75, -50, -25, 0, 25, 50, 75, 100]:
        _tick(x, major=(x in labeled))
        if x in labeled:
            ax.text(x, 0.25, labeled[x],
                    va='top', ha='center', fontsize=8,
                    fontfamily='sans-serif', color='#333333')

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out_path = os.path.join(TMP_DIR, "axis.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    _AXIS_IMG_PATH = out_path
    return out_path


def generate_legend_img():
    """
    Compact two-row legend rendered once and reused.

    Row 1 (blue)  – left/assembly side
    Row 2 (green) – right/RNA side
    """
    global _LEGEND_IMG_PATH
    if _LEGEND_IMG_PATH is not None:
        return _LEGEND_IMG_PATH

    fig, ax = plt.subplots(figsize=(BAR_FIG_W, 0.55), dpi=BAR_DPI)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    swatch_w, swatch_h = 0.06, 0.28
    gap                = 0.02
    label_kw = dict(va='center', fontsize=9, fontfamily='sans-serif', color='#222222')

    def _row(y_center, c_light, c_dark, label_left, label_right):
        y0   = y_center - swatch_h / 2
        # Light swatch
        x0_l = 0.5 - swatch_w - gap / 2
        ax.add_patch(mpatches.FancyBboxPatch(
            (x0_l, y0), swatch_w, swatch_h,
            boxstyle="round,pad=0.01",
            facecolor=c_light, edgecolor='white', linewidth=0.5))
        ax.text(x0_l - gap, y_center, label_left,
                ha='right', **label_kw)
        # Dark swatch
        x0_d = 0.5 + gap / 2
        ax.add_patch(mpatches.FancyBboxPatch(
            (x0_d, y0), swatch_w, swatch_h,
            boxstyle="round,pad=0.01",
            facecolor=c_dark, edgecolor='white', linewidth=0.5))
        ax.text(x0_d + swatch_w + gap, y_center, label_right,
                ha='left', **label_kw)

    _row(0.72, C_ASS_LIGHT, C_RNA_LIGHT,  "Assembled",  "RNA-Seq (Any)")
    _row(0.25, C_ANN_DARK, C_LNG_DARK,  "Annotated", "Long-Read RNA")

    # Divider between the two data sides
    ax.axvline(0.5, ymin=0.05, ymax=0.95,
               color=SPINE_COLOR, linewidth=0.8, linestyle='--')

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out_path = os.path.join(TMP_DIR, "legend.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    _LEGEND_IMG_PATH = out_path
    return out_path

_COLOR_SQUARES = {}

def generate_color_square(color):
    """
    Generate a small colored square image used instead of text headers
    for the numeric counts.
    """
    global _COLOR_SQUARES
    if color in _COLOR_SQUARES:
        return _COLOR_SQUARES[color]
    
    fig, ax = plt.subplots(figsize=(0.12, 0.12), dpi=BAR_DPI)
    ax.add_patch(mpatches.Rectangle((0, 0), 1, 1, facecolor=color, edgecolor='white', linewidth=0.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out_path = os.path.join(TMP_DIR, f"square_{color.replace('#', '')}.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    
    _COLOR_SQUARES[color] = out_path
    return out_path


# ── ETE3 layout & tree style ─────────────────────────────────────────────────
def create_layout_fn(ncbi, phylum_metadata, include_counts):
    def my_layout(node):
        if not node.is_leaf():
            return

        taxid      = int(node.name)
        taxon_name = ncbi.get_taxid_translator([taxid]).get(taxid, str(taxid))

        # Col 0 – taxon name ───────────────────────────────────────────────
        name_face = TextFace(f" {taxon_name}", fsize=10, ftype="times new roman", fstyle="italic")
        name_face.margin_right = 0 # 10
        node.add_face(name_face, column=0, position="aligned")

        if taxid not in phylum_metadata:
            return

        meta = phylum_metadata[taxid]

        # Col 1 – divergent bar chart ──────────────────────────────────────
        img_face = ImgFace(generate_bar_chart(taxid, meta))
        img_face.margin_left  = 5
        img_face.margin_right = 15
        node.add_face(img_face, column=1, position="aligned")

        # Col 2 – total organisms ──────────────────────────────────────────
        n_face = TextFace(f"{meta['n_rows']:,}", fsize=10, bold=True,
                          ftype="times new roman", tight_text=True)
        n_face.margin_right = 20
        node.add_face(n_face, column=2, position="aligned")

        if include_counts:
            # Helper to add a colored square and count value side-by-side securely in separate columns
            def _add_count_col(entries, organisms, color, col_idx_sq, col_idx_txt, is_last=False):
                # 1) Colored square
                sq_face = ImgFace(generate_color_square(color))
                sq_face.margin_left = 0 # 5 then changed to 0
                sq_face.margin_right = 3 # margin between square and its text
                node.add_face(sq_face, column=col_idx_sq, position="aligned")
                
                # 2) Count value: "Entries (Organisms)"
                txt_face = TextFace(f"{entries:,} ({organisms:,})", fsize=10, ftype="times new roman", tight_text=True)
                # txt_face.margin_right = 15 if is_last else 8
                txt_face.margin_right = 0
                node.add_face(txt_face, column=col_idx_txt, position="aligned")
            
            # Left counts mapped to specific colours (using discrete columns to avoid overlaps)
            _add_count_col(meta['s_ass'], meta['c_ass'], C_ASS_LIGHT, 3, 4)
            _add_count_col(meta['s_ann'], meta['c_ann'], C_ANN_DARK,  5, 6, is_last=True)
            
            # Right counts mapped to specific colours
            _add_count_col(meta['s_rna'], meta['c_rna'], C_RNA_LIGHT, 7, 8)
            _add_count_col(meta['s_lng'], meta['c_lng'], C_LNG_DARK,  9, 10, is_last=True)

    return my_layout


def configure_tree_style(my_layout, include_counts):
    ts = TreeStyle()
    ts.layout_fn        = my_layout
    ts.show_leaf_name   = False
    ts.force_topology   = True
    ts.draw_guiding_lines   = True
    ts.guiding_lines_type   = 2
    ts.guiding_lines_color  = "#c7c7c7"

    # Header Col 1 – legend (aligned with bar chart column)
    legend_face = ImgFace(generate_legend_img())
    legend_face.margin_left   = 5
    legend_face.margin_right  = 15
    legend_face.margin_bottom = 8
    ts.aligned_header.add_face(legend_face, column=1)

    # Footer Col 1 – axis ruler (aligned with bar chart column)
    axis_face = ImgFace(generate_axis_img())
    axis_face.margin_left  = 5
    axis_face.margin_right = 15
    ts.aligned_foot.add_face(axis_face, column=1)

    # Header Col 2 – "Number of organisms"
    org_header = TextFace("Number of\norganisms", fsize=10, bold=True,
                          ftype="times new roman", tight_text=True)
    org_header.margin_right  = 20
    org_header.margin_bottom = 10
    ts.aligned_header.add_face(org_header, column=2)

    if include_counts:
        # Add a unified header for the counts section
        # Stacked into two lines so its width matches the count text cells,
        # preventing ETE3 from widening the column and displacing the squares!
        counts_header = TextFace("Entries (Organisms)", fsize=10, bold=True,
                                 ftype="times new roman", tight_text=True)
        counts_header.margin_right = -100
        counts_header.margin_left = 0
        counts_header.margin_bottom = 0
        
        # Placing it in Column 6 (Annotation Unique Organism Text)
        ts.aligned_header.add_face(counts_header, column=6)

    return ts
