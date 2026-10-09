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
# PQ specification limits (from PQ documentation), drawn as horizontal reference lines
PQ_SPECS = {
    "Total Molecules":     (6_000_000, "6M"),
    "% Filtered Remapped": (37,        "37%"),
    "%FN> 500bp":          (11,        "11%"),
    "% FP":                (9,         "9%"),
    "Remap 20th%":         (140,       "140 kb"),
    "Raw_Coverage":        (75,        "75X"),
}
PQ_STYLE = dict(color="#444444", ls=":", lw=1.6, zorder=1)

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

    # PQ spec reference line + label at the right edge
    if metric in PQ_SPECS:
        val, lbl = PQ_SPECS[metric]
        ax.axhline(val, **PQ_STYLE)
        ax.annotate(f"PQ {lbl}", xy=(1, val), xycoords=("axes fraction", "data"),
                    xytext=(-2, 3), textcoords="offset points", ha="right", va="bottom",
                    fontsize=8, color=PQ_STYLE["color"])

    ax.set_title(metric, loc="left", fontweight="bold")
    ax.set_xlabel(TIME_COL)
    ax.set_xticks(tps)
    pad = 0.8 if len(tps) == 1 else 0.6
    ax.set_xlim(min(tps) - pad, max(tps) + pad)
    if df[metric].max() > 1e5:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1e6:g}M"))


def legend_handles(pq=True):
    h = [Patch(color=GROUP_COLORS[g], label=f"{g}: {group_label[g]}") for g in groups]
    h += [Line2D([], [], color="#555555", lw=2, label=f"Injection {inj}", **s)
          for inj, s in INJ_STYLE.items()]
    h += [Line2D([], [], color="#555555", alpha=ERR_ALPHA, lw=1.8, marker="_", ms=8,
                 mew=1.8, label="± 1 SD")]
    if pq:
        h += [Line2D([], [], label="PQ spec", **PQ_STYLE)]
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
fig.legend(handles=legend_handles(), loc="lower center", ncol=7,
           frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.02))
fig.suptitle("Detector shelf life — remap metrics by condition and injection",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0.05, 1, 0.97))
fig.savefig(OUT_DIR / "shelf_life_overview.png", dpi=200, bbox_inches="tight")
plt.show()

# %%
# Settings for instrument metric comparison
#region Inst Metrics
# Instrument metrics (per-injection run averages) plotted the same way as the remap
# metrics above. The run averages come from Instrument_Run_Metrics/instrument_run_metrics.py
# (_run_averages), so they match the "Average Values" table in the overnight/sequential reports.

# One entry per export folder -> shelf-life time point (months). Sub-folders are searched too
# (e.g. one folder per injection). Add the 3- and 6-month export folders here as they come in.
INST_EXPORT_DIRS = {
    r"\\proton\TechDevGroup\Users\Luce\LabTools\run_metric_exports\20261007_Shelf_Life_Expired_Detectors": 0,
}
INST_METRICS = ["Total Event Rate", "Channel Activity (%)", "Active Channel Count", "Signal RMS"]
INST_CODE_DIR = r"C:\Users\luce\Code\nabsys_code\Instrument_Run_Metrics"

# %%
# Load instrument exports and compute per-run averages

import sys
if INST_CODE_DIR not in sys.path:
    sys.path.insert(0, INST_CODE_DIR)
import instrument_run_metrics as irm   # importing doesn't generate its figures (guarded run cell)

irm.SHOW_INLINE = False

# Remap data gives each run its Group / Detector Condition / Injection
run_info = (combined_df[["Run ID", "Group", "Detector Condition", "Injection"]]
            .drop_duplicates("Run ID").set_index("Run ID"))

inst_rows = []
for export_dir, tp in INST_EXPORT_DIRS.items():
    dirs = [d for d, _, files in os.walk(export_dir)
            if any(f.lower().endswith(".csv") for f in files)]
    if not dirs:
        print(f"WARNING: no CSVs found under {export_dir}")
        continue
    # same read-in as the overnight report: ChannelData thinned to one row per channel per minute
    sys_m, ch_m, _ = irm.read_experiment(dirs, channel_per_minute=True)
    ch_m = irm.per_minute_rows(ch_m)
    for run_id in irm.unique_in_order(sys_m["RunID"]):
        sys_d = sys_m[sys_m["RunID"] == run_id]
        ch_d = ch_m[ch_m["RunID"] == run_id]
        if sys_d.empty or ch_d.empty:
            print(f"Skipping {run_id}: missing SystemMetrics or ChannelData")
            continue
        if run_id not in run_info.index:
            print(f"Skipping {run_id}: not in the remap data, so its Group is unknown")
            continue
        avgs = irm._run_averages(sys_d, ch_d)
        inst_rows.append({"Run ID": run_id, TIME_COL: tp, **run_info.loc[run_id].to_dict(),
                          **{m: avgs[m] for m in INST_METRICS}})
    del sys_m, ch_m   # ChannelData is large; free it before the next folder

inst_df = pd.DataFrame(inst_rows)
missing = sorted(set(run_info.index) - set(inst_df.get("Run ID", [])))
print(f"{len(inst_df)} runs with instrument metrics; {len(missing)} remap runs without exports yet")
inst_df

# %%
# Instrument metric summary statistics (mean, SD, min, max, n)

inst_summary = (inst_df.groupby(["Group", TIME_COL, "Injection"])[INST_METRICS]
                       .agg(["mean", "std", "min", "max", "count"]))
inst_summary.round(4)

# %%
# Instrument metrics - individual plots

for metric in INST_METRICS:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    plot_metric(ax, metric, df=inst_df)
    ax.set_ylabel(metric)
    ax.legend(handles=legend_handles(pq=False), frameon=False, fontsize=8,
              loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", metric.replace("%", "pct")).strip("_")
    fig.savefig(OUT_DIR / f"shelf_life_inst_{safe}.png", dpi=200, bbox_inches="tight")
    plt.show()

# %%
# Instrument metrics - overview grid

fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
for ax, metric in zip(axes.flat, INST_METRICS):
    plot_metric(ax, metric, df=inst_df)
fig.legend(handles=legend_handles(pq=False), loc="lower center", ncol=3,
           frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.04))
fig.suptitle("Detector shelf life — instrument metrics by condition and injection",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0.07, 1, 0.97))
fig.savefig(OUT_DIR / "shelf_life_inst_overview.png", dpi=200, bbox_inches="tight")
plt.show()
# endregion
