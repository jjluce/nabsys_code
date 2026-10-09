# %%
"""
Data analysis for the shelf life study of the expired detectors we received from San Diego.

Line plots of key remap metrics vs. shelf-life time point, by Group /
Detector Condition and Injection.
  - Line + large marker = mean (Injection A solid/circle, B dashed/square)
  - Error bars (same color, more transparent) = mean ± 1 SD
  - Faint small markers = individual runs
  - Points are "dodged" on the x-axis (A left / B right, groups spread within
    each) so error bars don't overlap.
"""

# %%
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

# %%
# Settings for remapping comparison
# region Remapping
# One entry per CSV -> shelf-life time point (months). Add the 3- and 6-month
# exports here as they come in. If a CSV already has a TIME_COL column, that wins.
CSV_FILES = {
    r"\\proton\TechDevGroup\Users\Luce\LabTools\sharedtools_outputs\20261005_155043_remap_stats-shelf_life_combined.csv": 0,
}
OUT_DIR = Path(r"\\proton\TechDevGroup\Users\Luce\Results\Shelf_Life_Figures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

METRICS = ["Total Molecules", "% Filtered Remapped", "% FP",
           "%FN> 500bp", "Remap 20th%", "Raw_Coverage"]
TIME_COL = "Time Point (months)"

# x-dodge (months): injection A left of the time point, B right; groups spread within
INJ_OFFSET = {"A": -0.2, "B": 0.2}
GROUP_DODGE = 0.03
INJ_STYLE = {"A": dict(ls="-",  marker="o"),
             "B": dict(ls="--", marker="s")}
ERR_ALPHA = 0.55        # error-bar transparency
POINT_ALPHA = 0.35      # individual-run markers

# Non-default palette (colorblind-validated blue / orange / aqua), fixed per group
GROUP_COLORS = {"A1": "#2a78d6", "A2": "#eb6834", "B": "#1baf7a"}
EXTRA_COLORS = ["#eda100", "#e87ba4", "#4a3aa7"]   # only used if new groups appear

plt.rcParams.update({
    "figure.dpi": 110,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#e3e3e3",
    "grid.linewidth": 0.8,
    "axes.edgecolor": "#888888",
    "axes.labelcolor": "#333333",
    "xtick.color": "#555555",
    "ytick.color": "#555555",
    "font.size": 10,
})

# %%
# Load data

frames = []
for path, tp in CSV_FILES.items():
    d = pd.read_csv(path)
    d["Source File"] = os.path.basename(path)
    if TIME_COL not in d.columns:
        d[TIME_COL] = tp
    frames.append(d)

combined_df = pd.concat(frames, ignore_index=True).dropna(subset=["Group"])
combined_df["Injection"] = combined_df["Injection"].str.strip().str.upper()
combined_df[METRICS] = combined_df[METRICS].apply(pd.to_numeric, errors="coerce")

print(f"{len(combined_df)} runs from {len(frames)} file(s)")
combined_df.groupby(["Group", "Detector Condition", TIME_COL, "Injection"]).size().rename("n runs")

# %%
# Group -> legend label, color, and x-dodge

groups = sorted(combined_df["Group"].unique())
group_label = (combined_df.drop_duplicates("Group")
                          .set_index("Group")["Detector Condition"].to_dict())
extra = iter(EXTRA_COLORS)
for g in groups:
    GROUP_COLORS.setdefault(g, next(extra))
group_offset = {g: (i - (len(groups) - 1) / 2) * GROUP_DODGE for i, g in enumerate(groups)}

# Summary statistics (mean, SD, min, max, n)

summary = (combined_df.groupby(["Group", TIME_COL, "Injection"])[METRICS]
                      .agg(["mean", "std", "min", "max", "count"]))
summary.round(2)

# Plotting helper

def plot_metric(ax, metric, df=combined_df):
    tps = sorted(df[TIME_COL].unique())
    for g in groups:
        color = GROUP_COLORS[g]
        for inj, style in INJ_STYLE.items():
            sub = df[(df["Group"] == g) & (df["Injection"] == inj)]
            if sub.empty:
                continue
            dx = INJ_OFFSET[inj] + group_offset[g]
            stats = sub.groupby(TIME_COL)[metric].agg(["mean", "std"]).dropna(subset=["mean"])
            x = stats.index.to_numpy(float) + dx
            mean, sd = stats["mean"].to_numpy(), stats["std"].fillna(0).to_numpy()

            # spread: ±1 SD error bars
            ax.errorbar(x, mean, yerr=sd, fmt="none", ecolor=color, alpha=ERR_ALPHA,
                        elinewidth=1.8, capsize=4, capthick=1.8, zorder=2)
            # individual runs
            ax.scatter(sub[TIME_COL] + dx, sub[metric], s=16, color=color,
                       alpha=POINT_ALPHA, marker=style["marker"], edgecolor="none", zorder=2)
            # mean (line connects time points)
            ax.plot(x, mean, color=color, lw=2, ls=style["ls"], marker=style["marker"],
                    ms=8, mec="white", mew=1.5, zorder=3)

    ax.set_title(metric, loc="left", fontweight="bold")
    ax.set_xlabel(TIME_COL)
    ax.set_xticks(tps)
    pad = 0.8 if len(tps) == 1 else 0.6
    ax.set_xlim(min(tps) - pad, max(tps) + pad)
    if df[metric].max() > 1e5:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1e6:.0f}M"))


def legend_handles():
    h = [Patch(color=GROUP_COLORS[g], label=f"{g}: {group_label[g]}") for g in groups]
    h += [Line2D([], [], color="#555555", lw=2, label=f"Injection {inj}", **s)
          for inj, s in INJ_STYLE.items()]
    h += [Line2D([], [], color="#555555", alpha=ERR_ALPHA, lw=1.8, marker="_", ms=8,
                 mew=1.8, label="± 1 SD")]
    return h

# %%
# Individual plots (one figure per metric)

for metric in METRICS:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    plot_metric(ax, metric)
    ax.set_ylabel(metric)
    ax.legend(handles=legend_handles(), frameon=False, fontsize=8,
              loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", metric.replace("%", "pct")).strip("_")
    fig.savefig(OUT_DIR / f"shelf_life_{safe}.png", dpi=200, bbox_inches="tight")
    plt.show()

# %%
# Overview grid (all metrics on one figure)

fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
for ax, metric in zip(axes.flat, METRICS):
    plot_metric(ax, metric)
fig.legend(handles=legend_handles(), loc="lower center", ncol=6,
           frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.02))
fig.suptitle("Detector shelf life — remap metrics by condition and injection",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0.05, 1, 0.97))
fig.savefig(OUT_DIR / "shelf_life_overview.png", dpi=200, bbox_inches="tight")
plt.show()

# %%
# Settings for instrument metric comparison
#region Inst Metrics
