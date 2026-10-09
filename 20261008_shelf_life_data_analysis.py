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
inst_sys_frames = []   # SystemMetrics kept for the collection-cycle overlays below
inst_ch_frames = []    # ChannelData (viability, Signal RMS) kept for the same
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
        inst_sys_frames.append(
            sys_d[["RunID", "Time_abs_sec", "TotalEventRate", "ActiveChannelCount"]]
            .assign(**{TIME_COL: tp}, **run_info.loc[run_id].to_dict()))
        inst_ch_frames.append(pd.DataFrame({
            "RunID": run_id, "Time_abs_sec": ch_d["Time_abs_sec"].to_numpy(),
            "ChannelID": ch_d["ChannelID"].to_numpy(),
            "Viable": irm.is_viable(ch_d["ViableChannel"]).to_numpy(),
            "SignalRMS": ch_d["SignalRMS"].to_numpy()}))
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

# %%
# Settings for collection-cycle overlays
# region Cycle Overlays
# Per data-collection cycle (a 2-min cycle, then ~30-min cycles separated by ~4-min clean cycles):
#   rows 1-3: systemwide Total Event Rate, Active Channel Count and Signal RMS (viable channels,
#             as in the run report), averaged per cycle, then across the runs of each condition
#   row 4:    channel viability - each cell is a channel x cycle, shaded in a condition's color by
#             the fraction of that condition's readings in which the channel was non-viable
#             (averaged over replicates, so 2 and 3 replicates shade on the same 0-1 scale)
# One column per shelf-life time point, one line / color per condition.

CYCLE_GAP_SEC = 60            # a break in SystemMetrics longer than this starts a new cycle
ALL_TIME_POINTS = [0, 3, 6]   # columns shown, even before a time point has data
INJ_GAP_WIDTH = 3             # width of the grey 1st > 2nd injection gap, in cycles
CYCLE_METRICS = {"TotalEventRate": "Total Event Rate (system)",
                 "ActiveChannelCount": "Active Channel Count",
                 "SignalRMS": "Signal RMS"}
SHOW_SD = False               # True adds a faint ±1 SD band across runs to each line
VIAB_MAX_ALPHA = 0.3          # opacity of a cell that is non-viable in every reading of every replicate

# %%
# Per-cycle averages

cyc = pd.concat(inst_sys_frames, ignore_index=True).sort_values(["RunID", "Time_abs_sec"])
for c in ("TotalEventRate", "ActiveChannelCount"):
    cyc[c] = pd.to_numeric(cyc[c], errors="coerce")
new_cycle = cyc.groupby("RunID", observed=True)["Time_abs_sec"].diff().fillna(np.inf) > CYCLE_GAP_SEC
cyc["Cycle"] = new_cycle.groupby(cyc["RunID"], observed=True).cumsum().astype(int)

# ChannelData -> cycle, using each run's cycle start times from SystemMetrics
cycle_starts = cyc[new_cycle.to_numpy()].groupby("RunID", observed=True)["Time_abs_sec"].apply(np.array)
chc = pd.concat(inst_ch_frames, ignore_index=True)
chc["Cycle"] = 0
for rid, starts in cycle_starts.items():
    m = chc["RunID"] == rid
    chc.loc[m, "Cycle"] = np.searchsorted(starts, chc.loc[m, "Time_abs_sec"].to_numpy() + 0.5, side="right")
chc = chc[chc["Cycle"] > 0]
chc = chc.merge(run_info.reset_index().rename(columns={"Run ID": "RunID"}), on="RunID")
chc[TIME_COL] = chc["RunID"].map(inst_df.set_index("Run ID")[TIME_COL])

keys = ["Group", "Detector Condition", TIME_COL, "Injection", "RunID", "Cycle"]
# 1) mean of each cycle, per run
run_cycles = (cyc.groupby(keys, observed=True)[["TotalEventRate", "ActiveChannelCount"]].mean()
                 .join(chc[chc["Viable"]].groupby(keys, observed=True)["SignalRMS"].mean())
                 .reset_index())
n_cyc = run_cycles.groupby("RunID")["Cycle"].max()
print("Cycles per run:", n_cyc.to_dict())

# 2) mean (and SD) across the runs of each condition
cond_cycles = (run_cycles.groupby(["Group", TIME_COL, "Injection", "Cycle"])[list(CYCLE_METRICS)]
                         .agg(["mean", "std", "count"]))

# viability: fraction non-viable per run/channel/cycle, then mean over that condition's replicates
nonviable = (chc.assign(NonViable=~chc["Viable"])
                .groupby(["Group", TIME_COL, "Injection", "RunID", "ChannelID", "Cycle"])["NonViable"].mean()
                .groupby(["Group", TIME_COL, "Injection", "ChannelID", "Cycle"]).mean())
n_channels = int(chc["ChannelID"].max())

# x positions: injection A cycles 1..nA, then the gap, then injection B (numbering continues)
n_a = int(run_cycles.loc[run_cycles["Injection"] == "A", "Cycle"].max() or 0)
n_b = int(run_cycles.loc[run_cycles["Injection"] == "B", "Cycle"].max() or 0)
n_x = n_a + INJ_GAP_WIDTH + n_b
def cycle_x(inj, c):
    return c if inj == "A" else n_a + INJ_GAP_WIDTH + c

# %%
# Collection-cycle overlay figure (3 time points x 4 rows) + each panel as its own figure
from matplotlib.colors import to_rgb

def draw_inj_gap(ax):
    g0, g1 = n_a + 0.5, n_a + INJ_GAP_WIDTH + 0.5
    ax.axvspan(g0, g1, color="#e6e6e6", lw=0, zorder=0.5)
    for g in (g0, g1):
        ax.axvline(g, color="#555555", ls="--", lw=1, zorder=4)
    ax.text((g0 + g1) / 2, 0.5, "1st > 2nd Inj Gap", transform=ax.get_xaxis_transform(),
            rotation=90, ha="center", va="center", fontsize=8, color="#666666", zorder=4)


def viability_image(tp):
    """RGBA image (channels x cycle positions). Each condition contributes
    alpha = VIAB_MAX_ALPHA x (fraction of its readings non-viable, averaged over replicates).
    The alphas add up, so with VIAB_MAX_ALPHA = 0.3 a channel dead in all three conditions
    reaches 0.9 total; the cell color is the alpha-weighted mix of the condition colors over white.
    Returns None if there is no data at this time point."""
    total_a = np.zeros((n_channels, n_x))
    color_sum = np.zeros((n_channels, n_x, 3))
    found = False
    for g in groups:
        rgb = np.array(to_rgb(GROUP_COLORS[g]))
        for inj in ("A", "B"):
            try:
                f = nonviable.loc[(g, tp, inj)]
            except KeyError:
                continue
            found = True
            a = np.zeros((n_channels, n_x))
            ch_idx = f.index.get_level_values("ChannelID").to_numpy() - 1
            x_idx = np.array([cycle_x(inj, k) for k in f.index.get_level_values("Cycle")]) - 1
            a[ch_idx, x_idx] = VIAB_MAX_ALPHA * f.to_numpy()
            total_a += a
            color_sum += a[..., None] * rgb
    if not found:
        return None
    total_a = np.clip(total_a, 0, 1)
    img = (1 - total_a[..., None]) * 1.0 + color_sum   # white background + weighted condition colors
    alpha = np.ones((n_channels, n_x, 1))
    alpha[:, n_a:n_a + INJ_GAP_WIDTH] = 0             # let the grey injection-gap band show through
    return np.concatenate([np.clip(img, 0, 1), alpha], axis=2)


def no_data(ax):
    ax.text(0.5, 0.8, "No data yet", transform=ax.transAxes, ha="center", va="center",
            fontsize=11, color="#999999", zorder=5,
            bbox=dict(facecolor="white", edgecolor="none", pad=3))


def draw_cycle_lines(ax, col, tp):
    """One condition-mean line per group (A and B injections). Returns True if anything was drawn."""
    draw_inj_gap(ax)
    has_data = False
    for g in groups:
        for inj in ("A", "B"):
            if (g, tp, inj) not in cond_cycles.index.droplevel("Cycle"):
                continue
            d = cond_cycles.loc[(g, tp, inj), col]
            x = np.array([cycle_x(inj, k) for k in d.index])
            ax.plot(x, d["mean"], color=GROUP_COLORS[g], lw=2, marker="o", ms=3.5, zorder=3)
            if SHOW_SD:
                sd = d["std"].fillna(0)
                ax.fill_between(x, d["mean"] - sd, d["mean"] + sd, color=GROUP_COLORS[g],
                                alpha=0.15, lw=0, zorder=2)
            has_data = True
    if not has_data:
        no_data(ax)
    return has_data


def draw_viability(ax, tp):
    img = viability_image(tp)
    if img is not None:
        ax.imshow(img, aspect="auto", origin="lower", interpolation="nearest", zorder=1,
                  extent=(0.5, n_x + 0.5, 0.5, n_channels + 0.5))
    else:
        no_data(ax)
    draw_inj_gap(ax)
    ax.set_ylim(0.5, n_channels + 0.5)
    ax.grid(False)
    return img is not None


def format_cycle_axis(ax):
    for inj, x0 in (("Inj A", 1), ("Inj B", n_a + INJ_GAP_WIDTH + 1)):
        ax.text(x0, 1.01, inj, transform=ax.get_xaxis_transform(), fontsize=8, color="#555555")
    ax.set_xticks(tick_x, [str(t) for t in tick_cycles])
    ax.set_xlim(0.5, n_x + 0.5)
    ax.tick_params(labelleft=True)


tick_cycles = [c for c in range(1, n_a + n_b + 1) if c == 1 or c % 8 == 0]
tick_x = [cycle_x("A", c) if c <= n_a else cycle_x("B", c - n_a) for c in tick_cycles]
VIAB_LABEL = "Channel (shaded = non-viable)"
VIAB_NOTE = ("Viability: darker = channel non-viable in more of that condition's readings "
             f"(fraction per cycle, averaged over replicates; max {VIAB_MAX_ALPHA:g} per condition)")
cycle_handles = [Line2D([], [], color=GROUP_COLORS[g], lw=2, marker="o", ms=4,
                        label=f"{g}: {group_label[g]}") for g in groups]
panels = [(col, label) for col, label in CYCLE_METRICS.items()] + [("Viability", VIAB_LABEL)]

# %%
# Overlay grid (all 12 panels)

n_rows = len(panels)
fig, axes = plt.subplots(n_rows, len(ALL_TIME_POINTS),
                         figsize=(5.5 * len(ALL_TIME_POINTS), 3.6 * n_rows),
                         sharex=True, sharey="row", squeeze=False)
for c, tp in enumerate(ALL_TIME_POINTS):
    for r, (col, label) in enumerate(panels):
        ax = axes[r, c]
        draw_viability(ax, tp) if col == "Viability" else draw_cycle_lines(ax, col, tp)
        format_cycle_axis(ax)
        if c == 0:
            ax.set_ylabel(label)
    axes[0, c].set_title(f"{tp} months", loc="left", fontweight="bold", pad=14)
    axes[-1, c].set_xlabel("Collection cycle")

fig.legend(handles=cycle_handles, loc="lower center", ncol=len(cycle_handles), frameon=False,
           fontsize=9, bbox_to_anchor=(0.5, 0.0))
fig.text(0.5, -0.012, VIAB_NOTE, ha="center", fontsize=8.5, color="#555555")
fig.suptitle("Detector shelf life — systemwide metrics per collection cycle (mean of runs per condition)",
             x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout(rect=(0, 0.035, 1, 0.98))
fig.savefig(OUT_DIR / "shelf_life_cycle_overlay.png", dpi=200, bbox_inches="tight")
plt.show()

# %%
# Individual panels (one figure per metric per time point; time points without data are skipped)

for tp in ALL_TIME_POINTS:
    for col, label in panels:
        fig, ax = plt.subplots(figsize=(9, 4.5))
        drawn = draw_viability(ax, tp) if col == "Viability" else draw_cycle_lines(ax, col, tp)
        if not drawn:
            plt.close(fig)
            continue
        format_cycle_axis(ax)
        ax.set_ylabel(label)
        ax.set_xlabel("Collection cycle")
        name = "Channel Viability" if col == "Viability" else CYCLE_METRICS[col]
        ax.set_title(f"{name} — {tp} months", loc="left", fontweight="bold", pad=14)
        ax.legend(handles=cycle_handles, frameon=False, fontsize=8,
                  loc="upper left", bbox_to_anchor=(1.01, 1))
        if col == "Viability":
            fig.text(0.01, -0.02, VIAB_NOTE, fontsize=7.5, color="#555555")
        fig.tight_layout()
        safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        fig.savefig(OUT_DIR / f"shelf_life_cycle_{safe}_{tp}mo.png", dpi=200, bbox_inches="tight")
        plt.show()
# endregion

# %%
