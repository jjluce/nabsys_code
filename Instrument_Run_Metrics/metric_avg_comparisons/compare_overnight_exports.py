# %% [markdown]
# # Compare overnight exports
# Rebuilds the overnight instrument-metrics figure from two (or more) exports of the same run and
# compares them, e.g.
#   * export_run_metrics.bat      -> exports\<SampleID>      (ChannelData: one snapshot per minute)
#   * export_run_metrics_avg.bat  -> exports_avg\<SampleID>  (ChannelData: averaged over each minute;
#                                   this .bat is in this folder, metric_avg_comparisons)
#   * optionally the original full export (every reading) as a reference.
#
# Outputs (in OUT_DIR):
#   * one overnight figure per export, labelled with the export name
#   * <run>_export_comparison_<time>.jpg  - per-minute traces of each metric, one line per export,
#                                           plus how often the exports disagree on channel viability
#   * <run>_export_comparison_<time>.csv  - the table averages for each export and the differences
#
# Lives in Instrument_Run_Metrics\metric_avg_comparisons\ and uses the figure code in
# ..\instrument_run_metrics.py (the parent folder), so the figures match that script.
# Run the cells top to bottom (VS Code "Run Cell"), or
#     python metric_avg_comparisons\compare_overnight_exports.py   (from Instrument_Run_Metrics)

# %% Settings
# label -> export folder (the first one is the reference that the others are compared against)
EXPORTS = {
    "Snapshot (1 per min)": r"\\proton\TechDevGroup\Users\Luce\LabTools\exports\TC043_D008-02B63894w16-205B21a",
    "Average (per min)": r"\\proton\TechDevGroup\Users\Luce\LabTools\exports_avg\TC043_D008-02B63894w16-205B21a",
    # "Full export": r"C:\Users\luce\Code\data\TC043_D008-02B63894w16-205B21a",
}
OUT_DIR = r"\\proton\TechDevGroup\Users\Luce\Results\Instrument_Report_Analysis"
USE_PROTOCOL_SHEET = False   # Google Sheets protocol lookup (needs gspread credentials)
SHOW_INLINE = True           # also display figures when running in cells
# Folder holding instrument_run_metrics.py (None = find it automatically: the parent of this
# file's folder, i.e. Instrument_Run_Metrics)
IRM_DIR = None

# %% Imports
import os
import sys
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt


def _this_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:  # running in an interactive window
        return os.getcwd()


def _find_irm_dir():
    """instrument_run_metrics.py is one folder up (Instrument_Run_Metrics); also accept this folder
    or the working folder, e.g. if VS Code's Interactive Window starts somewhere else."""
    here, cwd = _this_dir(), os.getcwd()
    candidates = [IRM_DIR, os.path.join(here, os.pardir), here, cwd, os.path.join(cwd, os.pardir)]
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "instrument_run_metrics.py")):
            return os.path.abspath(d)
    raise FileNotFoundError("Can't find instrument_run_metrics.py; set IRM_DIR in the settings cell to "
                            "the Instrument_Run_Metrics folder.")


sys.path.insert(0, _find_irm_dir())
import instrument_run_metrics as irm  # noqa: E402

irm.SHOW_INLINE = SHOW_INLINE
COLORS = ["#3B6FB6", "#E07B39", "#5A9E55", "#8E5BA8"]  # one per export, in EXPORTS order


# %% Load each export
def folder_size_mb(folder):
    return sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder)
               if f.lower().endswith(".csv")) / 1e6


def load_export(folder):
    sm, cd, rd = irm.read_experiment(folder, channel_per_minute=True)
    cd = irm.per_minute_rows(cd)  # what the overnight figure uses (averaged exports: every row)
    return sm, cd, rd


data = {}
for label, folder in EXPORTS.items():
    print(f"--- {label}: {folder}")
    data[label] = dict(folder=folder, size_mb=folder_size_mb(folder), **dict(zip(["sm", "cd", "rd"],
                                                                                load_export(folder))))
labels = list(data)
ref = labels[0]
run_ids = [r for r in irm.find_run_ids(EXPORTS[ref])
           if all((data[lab]["sm"]["RunID"] == r).any() for lab in labels)]
print("Runs found in every export:", run_ids)

stamp = datetime.now().strftime("_%Y%m%d_%H%M%S")
os.makedirs(OUT_DIR, exist_ok=True)
protocol_settings = irm._protocol_settings_or_none(USE_PROTOCOL_SHEET)


def run_slice(label, run_id):
    """One run's SystemMetrics and ChannelData from an export, ChannelData on the SystemMetrics clock."""
    d = data[label]
    sys_d = d["sm"][d["sm"]["RunID"] == run_id]
    ch_d = irm.align_to_system_clock(sys_d, d["cd"][d["cd"]["RunID"] == run_id])
    return sys_d, ch_d


def slug(label):
    import re
    return re.sub(r"[^0-9a-zA-Z]+", "_", label).strip("_").lower()


# %% Overnight figure from each export
saved = []
for run_id in run_ids:
    for label in labels:
        d = data[label]
        sys_d, ch_d = run_slice(label, run_id)
        fig = irm._overnight_run_figure(run_id, sys_d, ch_d, d["rd"], protocol_settings)
        fig.text(0.005, 0.995, f"Export: {label}", ha="left", va="top", fontsize=11,
                 fontweight="bold", color=COLORS[labels.index(label) % len(COLORS)])
        path = os.path.join(OUT_DIR, f"{run_id}_overnight_{slug(label)}{stamp}.jpg")
        saved.append(irm._save(fig, path))


# %% Summary table: the overnight table's averages for each export
def per_minute_traces(sys_d, ch_d):
    """Across-channel means at each minute, computed the way the overnight panels compute them."""
    viable = irm.is_viable(ch_d["ViableChannel"])
    chv = ch_d[viable]
    g = ch_d.groupby("Time_sec")
    out = pd.DataFrame({"Channel Activity (%)": 100 * viable.groupby(ch_d["Time_sec"]).mean()})
    out["Total Event Rate (channel mean)"] = chv.groupby("Time_sec")["TotalEventRate"].mean()
    out["Baseline (mV)"] = chv.groupby("Time_sec")["Baseline"].mean()
    lv = chv[chv["LevelOne"] != irm.LEVEL_ONE_SENTINEL]
    out["Level 1 (uV)"] = lv.groupby("Time_sec")["LevelOne"].mean()
    rms = chv[chv["SignalRMS"] < 0.08]
    out["Signal RMS"] = rms.groupby("Time_sec")["SignalRMS"].mean()
    out["Time"] = g["Time"].min()
    return out.reset_index()


rows = []
for run_id in run_ids:
    for label in labels:
        d = data[label]
        sys_d, ch_d = run_slice(label, run_id)
        rows.append({"Run": run_id, "Export": label, "Export size (MB)": round(d["size_mb"], 1),
                     "ChannelData rows": len(ch_d), **irm._run_averages(sys_d, ch_d)})
summary = pd.DataFrame(rows)
metric_cols = irm.AVG_COLS
diff = summary.copy()
for run_id in run_ids:
    base = summary[(summary["Run"] == run_id) & (summary["Export"] == ref)][metric_cols].iloc[0]
    m = diff["Run"] == run_id
    diff.loc[m, metric_cols] = summary.loc[m, metric_cols].astype(float) - base.astype(float).values
diff["Export"] = diff["Export"] + f" minus {ref}"
diff = diff[diff["Export"] != f"{ref} minus {ref}"]
table = pd.concat([summary, diff], ignore_index=True)
with pd.option_context("display.max_columns", None, "display.width", 250):
    print(table.to_string(index=False))
for run_id in run_ids:
    table[table["Run"] == run_id].to_csv(
        os.path.join(OUT_DIR, f"{run_id}_export_comparison{stamp}.csv"), index=False)


# %% Comparison figure: per-minute traces from each export, overlaid
def viability_disagreement(ch_a, ch_b):
    """% of channel-minutes where two exports disagree on ViableChannel, per minute.
    A snapshot reading is paired with the averaged minute that contains it (averaged exports'
    minutes start at each collection block, so their timestamps differ from the snapshots')."""
    a_avg, b_avg = "Samples" in ch_a.columns, "Samples" in ch_b.columns
    cols = ["ChannelID", "Time_abs_sec", "Time", "ViableChannel"]
    a, b = ch_a[cols].copy(), ch_b[cols].copy()
    a["va"] = irm.is_viable(a["ViableChannel"]).to_numpy()
    b["vb"] = irm.is_viable(b["ViableChannel"]).to_numpy()
    if a_avg and not b_avg:            # points = b (snapshots), windows = a (averaged minutes)
        pts, win, direction, tol = b, a, "backward", 59.999
    elif b_avg and not a_avg:
        pts, win, direction, tol = a, b, "backward", 59.999
    else:                              # same kind of export: match the same timestamps
        pts, win, direction, tol = a, b, "nearest", 1.0
    pts = pts.sort_values("Time_abs_sec")
    win = win.drop(columns=["Time"]).sort_values("Time_abs_sec")
    m = pd.merge_asof(pts, win, on="Time_abs_sec", by="ChannelID", direction=direction,
                      tolerance=tol, suffixes=("", "_w")).dropna(subset=["va", "vb"])
    m["diff"] = m["va"].astype(bool) != m["vb"].astype(bool)
    m["minute"] = (m["Time"] * 60).round()
    per_min = m.groupby("minute").agg(Time=("Time", "min"), pct=("diff", "mean")).reset_index()
    per_min["pct"] *= 100
    return per_min, 100 * m["diff"].mean(), len(m)


panels = ["Channel Activity (%)", "Total Event Rate (channel mean)", "Baseline (mV)",
          "Level 1 (uV)", "Signal RMS"]
for run_id in run_ids:
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 8.5), sharex=True)
    traces = {}
    for k, label in enumerate(labels):
        d = data[label]
        tr = per_minute_traces(*run_slice(label, run_id))
        traces[label] = tr
        tr = tr.sort_values("Time").reset_index(drop=True)
        # break lines across cleaning gaps (> 2 min): add an empty point inside each gap
        gap_at = tr.index[tr["Time"].diff() > 2 / 60]
        if len(gap_at):
            breaks = pd.DataFrame({"Time": tr.loc[gap_at, "Time"].to_numpy() - 1 / 3600})
            tr = pd.concat([tr, breaks], ignore_index=True).sort_values("Time")
        for ax, col in zip(axes.flat, panels):
            ax.plot(tr["Time"], tr[col], color=COLORS[k % len(COLORS)], lw=0.8, alpha=0.85, label=label)
    for ax, col in zip(axes.flat, panels):
        ax.set_title(col, fontsize=11)
        ax.grid(True, color="#E5E5E5", lw=0.6)
        ax.set_axisbelow(True)
    axes.flat[0].legend(fontsize=9, frameon=False)

    ax = axes.flat[5]
    ch_ref = run_slice(ref, run_id)[1]
    notes = []
    for k, label in enumerate(labels[1:], start=1):
        ch_o = run_slice(label, run_id)[1]
        per_min, overall, n = viability_disagreement(ch_ref, ch_o)
        ax.plot(per_min["Time"], per_min["pct"], color=COLORS[k % len(COLORS)], lw=0.8,
                label=f"{label} vs {ref}")
        notes.append(f"{label}: {overall:.2f}% of {n:,} channel-minutes")
        print(f"{run_id}: viability disagreement, {label} vs {ref}: {overall:.2f}% of {n:,} channel-minutes")
    ax.set_title("Channel viability disagreement (%)", fontsize=11)
    ax.text(0.02, 0.97, "\n".join(notes), transform=ax.transAxes, va="top", fontsize=8)
    ax.grid(True, color="#E5E5E5", lw=0.6)
    ax.set_axisbelow(True)
    for ax in axes[1]:
        ax.set_xlabel("Run Time (hrs)")
    fig.suptitle(f"{run_id}: per-minute means by export (viable channels)", fontsize=13)
    fig.tight_layout()
    saved.append(irm._save(fig, os.path.join(OUT_DIR, f"{run_id}_export_comparison{stamp}.jpg")))

print("\n".join(saved))
