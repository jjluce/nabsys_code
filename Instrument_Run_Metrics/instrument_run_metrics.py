# %% [markdown]
# # Instrument Run Metrics
# Python port of instrument_run_metrics.R, laid out as `# %%` cells (VS Code "Run Cell" / Interactive Window,
# Spyder, or PyCharm scientific mode). Run the cells top to bottom; set your options in the **Run settings** cell.
#
# Report types (MODE):
#   * "overnight"  - overnight_run_plots(): single-run version (e.g. 16 h data collection),
#                    per-channel data, one JPG per run ID found.
#   * "sequential" - sequential_run_plots(): the overnight figure, but with every injection onto the
#                    same detector (wafer-die) appended end to end on one shared clock (gaps between
#                    runs are kept), one table row per injection. One JPG per detector.
#   * "overlay"    - overlay_run_plots(): overlay version (e.g. instrument audit, tag titration),
#                    system-wide means for multiple injections onto the same detector, each starting
#                    at time 0. One JPG covering everything read in.
#
# Expected input: CSVs (with header rows) whose names contain SystemMetrics, ChannelData and
# RunData, e.g. ChannelData_<SampleID>.csv. EXPERIMENT_DIR can be one folder or a list of folders
# (e.g. one export folder per injection); files from all of them are combined.
#
# Packages: pandas, numpy, matplotlib, statsmodels (geom_smooth equivalent), gspread (Google Sheets).
# tkinter (file picker) ships with standard Python on Windows.

# %% Run settings
MODE = "sequential"           # "overnight", "sequential" or "overlay"
EXPERIMENT_DIR = r"C:\Users\luce\Code\data\combined"       # e.g. r"\\PROTON\TechDevGroup\...\20250429_tag_titration_human"; None = file picker
OUT_DIR = r"\\proton\TechDevGroup\Users\Luce\Results\Instrument_Report_Analysis"               # None = OUTPUT_BASE below, else the experiment folder
USE_PROTOCOL_SHEET = False    # overnight only: look up protocol settings in Google Sheets
                             # (needs %APPDATA%\gspread\credentials.json; skipped with a warning if missing)
SHOW_INLINE = True           # also display each figure when running in cells
# EXPERIMENT_DIR can also be a list of folders, e.g.
# EXPERIMENT_DIR = [r"C:\Users\luce\Code\data\TC043_D008-02B63894w16-205B21a",
#                   r"C:\Users\luce\Code\data\TC043_D008-02B63894w16-205B21b"]

# %% Imports
import os
import re
import textwrap
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.ticker

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


# %% Constants
# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------

# OUTPUT_BASE was a global defined outside the R script (used as paste0(OUTPUT_BASE, ...)).
# Set it to a folder here, or leave as None to save next to the input files. --out overrides it.
OUTPUT_BASE = None

PROTOCOL_SHEET_ID = "1w2ZVkmQjrU-1PeBAFNb9JDVsSd3hwGHqFD04JFTVQEw"

# NB, through mid-Nov 2025 this value had been 600; changed to 400 to roughly coincide with an
# OhmX controller software change.
LEVEL_ONE_SENTINEL = 400

JPG_DPI = 300  # ggsave default

# R colour names differ from matplotlib's: R "green" is #00FF00 and R "gray" is #BEBEBE
# (matplotlib's are the darker #008000 / #808080). Use R's values to match the R figures.
R_GREEN = "#00FF00"
R_GRAY = "#BEBEBE"

# Sequential mode: gaps between injections longer than GAP_BRIDGE_MIN_HR are drawn as a short
# break GAP_BRIDGE_WIDTH_HR wide; tick labels keep the real run time.
GAP_BRIDGE_MIN_HR = 2.0
GAP_BRIDGE_WIDTH_HR = 1.0


# %% Helpers (stand-ins for tidyverse / ggplot behaviour)
# --------------------------------------------------------------------------------------------------
# Small helpers (stand-ins for tidyverse / ggplot behaviour)
# --------------------------------------------------------------------------------------------------

def concat_csv_files(files, **read_csv_kwargs):
    """Read and row-bind CSVs, adding a `filename` column (basename).
    concat_csv_files() was not defined in the R script; this assumes it behaved like
    bind_rows(lapply(files, \\(f) read_csv(f) |> mutate(filename = basename(f))))."""
    frames = []
    for f in files:
        d = pd.read_csv(f, low_memory=False, **read_csv_kwargs)
        d["filename"] = os.path.basename(f)
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["filename"])
    out = pd.concat(frames, ignore_index=True, sort=False)
    out["filename"] = out["filename"].astype("category")
    return out


def is_viable(s):
    """ViableChannel == "TRUE" regardless of whether pandas read it as bool or text."""
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False).astype(bool)  # fast path; avoids building millions of strings
    return s.astype(str).str.strip().str.upper() == "TRUE"


def hue_pal(n, h=(15, 375), c=100, l=65):
    """ggplot2's default discrete palette (scales::hue_pal), so colours match the R output."""
    if n <= 0:
        return []
    h0, h1 = h
    if (h1 - h0) % 360 < 1:
        h1 -= 360 / n
    hues = np.linspace(h0, h1, n) % 360
    return [_hcl_to_hex(hh, c, l) for hh in hues]


def _hcl_to_hex(h, c, l):
    # polar LUV -> XYZ (D65) -> sRGB, as grDevices::hcl does
    xn, yn, zn = 95.047, 100.000, 108.883
    u_ = c * np.cos(np.radians(h))
    v_ = c * np.sin(np.radians(h))
    y = yn * (((l + 16) / 116) ** 3 if l > 8 else l / 903.3)
    t = xn + 15 * yn + 3 * zn
    un, vn = 4 * xn / t, 9 * yn / t
    u = u_ / (13 * l) + un
    v = v_ / (13 * l) + vn
    x = 9.0 * y * u / (4 * v)
    z = -x / 3 - 5 * y + 3 * y / v
    x, y, z = x / 100, y / 100, z / 100
    rgb = [3.240479 * x - 1.537150 * y - 0.498535 * z,
           -0.969256 * x + 1.875992 * y + 0.041556 * z,
           0.055648 * x - 0.204043 * y + 1.057311 * z]

    def gamma(u):
        u = 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055
        return int(round(255 * min(max(u, 0), 1)))

    return "#{:02X}{:02X}{:02X}".format(*[gamma(u) for u in rgb])


def seq(lo, hi, by):
    """R's seq(lo, hi, by=by)."""
    if hi < lo:
        return np.array([lo])
    return np.arange(lo, hi + by * 1e-9, by)


def within(s, lo, hi):
    """ggplot scale limits drop out-of-range values (rather than just clipping the view)."""
    return s.between(lo, hi)


def set_scale(ax, axis, lo, hi, breaks=None, expand=0.05):
    """scale_[xy]_continuous(limits=c(lo,hi), breaks=...) with ggplot's default 5% expansion."""
    pad = (hi - lo) * expand if hi > lo else 0.5
    if axis == "x":
        ax.set_xlim(lo - pad, hi + pad)
        if breaks is not None:
            ax.set_xticks(breaks)
    else:
        ax.set_ylim(lo - pad, hi + pad)
        if breaks is not None:
            ax.set_yticks(breaks)


def jitter(values, rng, amount=None):
    """geom_jitter default: +/- 40% of the data resolution."""
    v = np.asarray(values, dtype=float)
    if amount is None:
        u = np.unique(v[~np.isnan(v)])
        res = np.min(np.diff(u)) if len(u) > 1 else 1.0
        amount = 0.4 * res
    return v + rng.uniform(-amount, amount, size=len(v))


def lowess_smooth(x, y, n_out=80):
    """Stand-in for geom_smooth(). ggplot uses mgcv::gam(y ~ s(x, bs="cs")) for >= 1000 points;
    LOWESS gives a very similar curve here. (No standard-error ribbon is drawn.)"""
    from statsmodels.nonparametric.smoothers_lowess import lowess
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 10:
        return x, y
    rng = x.max() - x.min()
    fit = lowess(y, x, frac=0.3, it=0, delta=0.005 * rng, return_sorted=True)
    grid = np.linspace(x.min(), x.max(), n_out)
    return grid, np.interp(grid, fit[:, 0], fit[:, 1])


def wrap_dims(n):
    """ggplot2::wrap_dims - facet_wrap's default grid size."""
    ncol = int(np.ceil(np.sqrt(n)))
    nrow = int(np.ceil(n / ncol))
    return nrow, ncol


def unique_in_order(s):
    return list(pd.unique(s.dropna()))


def fmt_value(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def choose_experiment_dir():
    """file.choose() + dirname(): pick any file in the experiment folder."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(title="Pick any file in the experiment folder")
    root.destroy()
    if not path:
        raise SystemExit("No file chosen.")
    return os.path.dirname(path)


def as_dir_list(experiment_dir):
    """EXPERIMENT_DIR may be one folder, a list/tuple of folders, or None (file picker)."""
    if experiment_dir is None:
        return [choose_experiment_dir()]
    if isinstance(experiment_dir, (str, os.PathLike)):
        return [os.fspath(experiment_dir)]
    return [os.fspath(d) for d in experiment_dir]


def output_prefix(experiment_dirs, out_dir):
    """Default output folder: out_dir, else OUTPUT_BASE, else the (first) experiment folder."""
    base = out_dir or OUTPUT_BASE or as_dir_list(experiment_dirs)[0]
    os.makedirs(base, exist_ok=True)
    return base


def list_files(experiment_dirs, pattern):
    """list.files(dir, pattern=..., full.names=TRUE) over one or more folders - regex on file names.
    A file name found in more than one folder is only used once (first folder wins)."""
    rx = re.compile(pattern)
    seen, out = set(), []
    for d in as_dir_list(experiment_dirs):
        for f in sorted(os.listdir(d)):
            path = os.path.join(d, f)
            if not (rx.search(f) and os.path.isfile(path)):
                continue
            if f in seen:
                print(f"WARNING: {f} found in more than one folder; using the first copy only.")
                continue
            seen.add(f)
            out.append(path)
    return out


def find_run_ids(experiment_dirs):
    """Sample IDs present: between Data_/Metrics_ and .csv (tolerates sample-id typos)."""
    run_ids = []
    for path in list_files(experiment_dirs, r"(?:Data|Metrics)_.+\.csv$"):
        rid = _first(r"(?:Data|Metrics)_(.+)(?=\.csv)", os.path.basename(path))
        if rid is not None and rid not in run_ids:
            run_ids.append(rid)
    return run_ids

def show_figure(fig):
    """Display a figure inline when running in cells (VS Code / Jupyter); no-op from a plain terminal."""
    if not SHOW_INLINE:
        return
    try:
        from IPython import get_ipython
        from IPython.display import display
        if get_ipython() is not None:
            display(fig)
    except ImportError:
        pass


# %% Run metadata from the sample ID, and Time fields
# --------------------------------------------------------------------------------------------------
# Helper: run metadata from the sample ID, and Time fields
# --------------------------------------------------------------------------------------------------

def _first(rx, s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    m = re.search(rx, s)
    if m is None:
        return None
    return m.group(1) if m.groups() else m.group(0)


def _parse_run_id(filename):
    run_id = _first(r"(?:Metrics_|Data_)(.+)(?=\.csv)", filename)  # between prefix and .csv
    if run_id is None:
        return dict(RunID=None, Sample=None, Die=None, Wafer=None, Instrument=None, Injection=None)
    sample = _first(r"^.+?-.+?(?=-)", run_id)        # start of RunID to second dash
    die = run_id[26:29] or None                       # str_sub(RunID, 27, 29)  (still positional)
    wafer = _first(r"[Ww].+(?=-)", run_id)            # W/w up to (last) following dash
    instrument = run_id[23:26] or None                # str_sub(RunID, 24, 26)  (still positional)
    # Injection comes from the last dash-separated segment only (e.g. "205B21a" -> "a",
    # "205B21a_rerun" -> "a_rerun"); sample IDs like "TC043_D008-..." have underscores earlier on.
    tail = run_id.rsplit("-", 1)[-1]
    if "_" in tail:
        injection = _first(r"[A-Za-z]_.*$", tail)  # last letter before underscore to end
    else:
        injection = _first(r"[A-Za-z]$", tail)     # last letter
    if injection is None:
        injection = tail  # fall back to the whole segment so runs never silently drop out
    return dict(RunID=run_id, Sample=sample, Die=die, Wafer=wafer,
                Instrument=instrument, Injection=injection)


def run_metrics_metadata_markup(df):
    df = df.rename(columns={"TimeStamp": "Timestamp"})  # ChannelData uses TimeStamp

    meta = pd.DataFrame([dict(filename=f, **_parse_run_id(f)) for f in df["filename"].unique()])
    meta["InjectionSample"] = meta["Injection"].astype(str) + " " + meta["Sample"].astype(str)
    meta["WaferDie"] = meta["Wafer"].astype(str) + "-" + meta["Die"].astype(str)
    df = df.drop(columns=[c for c in meta.columns if c != "filename" and c in df.columns])
    meta = meta.set_index("filename")
    fn = df["filename"].astype(str)
    for col in meta.columns:  # categoricals: one copy of each label instead of one per row
        df[col] = fn.map(meta[col]).astype("category")

    # Time fields, per file
    ts = df["Timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        secs = ts.astype(float)
    else:
        parsed = pd.to_datetime(ts, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert(None)
        secs = (parsed - pd.Timestamp("1970-01-01")).dt.total_seconds()
    df["Time_abs_sec"] = secs  # absolute clock (used to put several runs on one time axis)
    t0 = secs.groupby(df["filename"], observed=True).transform("min")
    df["Time_min"] = t0
    time_sec = secs - t0
    df["Time_minutes"] = time_sec / 60
    df["Time"] = time_sec / 3600
    df["Time_sec"] = np.round(time_sec, 0)  # R round() is also round-half-to-even
    return df


# %% Protocol settings from Google Sheets
# --------------------------------------------------------------------------------------------------
# Helper: protocol settings from Google Sheets
# --------------------------------------------------------------------------------------------------

def _read_sheet(worksheet_title):
    """googlesheets4::read_sheet equivalent via gspread.
    First run opens a browser for Google OAuth; requires a desktop OAuth client file at
    %APPDATA%\\gspread\\credentials.json (see https://docs.gspread.org/en/latest/oauth2.html)."""
    import gspread
    gc = gspread.oauth()
    ws = gc.open_by_key(PROTOCOL_SHEET_ID).worksheet(worksheet_title)
    values = ws.get_all_values()
    d = pd.DataFrame(values[1:], columns=values[0])
    d = d.loc[:, d.columns != ""]
    d = d.replace("", np.nan).dropna(how="all")
    return d


def build_protocol_settings_df():
    s11 = _read_sheet("S11 - Automated Sample with Baselines")
    s11 = pd.DataFrame({
        "ProtocolName": "S11-Automated Sample Run with Baselines",
        "SettingsGroup": s11["Settings File Name"],
        "Target Baseline (mV)": s11["TargetBL"],
        "Applied Pressure (psi)": s11["Collect\nPressure"],
    })
    s15 = _read_sheet("S15 - Automated Sample Run Static Bias")
    s15 = pd.DataFrame({
        "ProtocolName": "S15-Automated Sample Run Static Bias",
        "SettingsGroup": s15["Settings File Name"],
        "Target Bias (V)": s15["Target Bias"],
        "Applied Pressure (psi)": s15["Collect\nPressure"],
    })
    out = pd.concat([s11, s15], ignore_index=True, sort=False)
    out = out[["ProtocolName", "SettingsGroup", "Target Baseline (mV)",
               "Applied Pressure (psi)", "Target Bias (V)"]]
    return out.astype("object")


# %% Shared read-in
# --------------------------------------------------------------------------------------------------
# Shared read-in
# --------------------------------------------------------------------------------------------------

RUN_DATA_COLS = ["SampleID", "ProtocolName", "ReagentLot", "SettingsGroup",
                 "DetectorLotNumber", "DetectorWaferID", "DetectorDieNumber"]


def read_run_data(files):
    """RunData is small but its last column (ChannelIDs) is a long quoted list that has been seen
    truncated ("...", no closing quote), which breaks the CSV parser. Only RUN_DATA_COLS are used,
    so repair an unbalanced quote if needed and keep just those columns."""
    import io
    frames = []
    for f in files:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        if text.count('"') % 2:
            text = text.rstrip("\r\n") + '"\n'
            print(f"WARNING: {os.path.basename(f)} has an unclosed quote (truncated ChannelIDs?); repaired.")
        d = pd.read_csv(io.StringIO(text), dtype=str)
        d = d[[c for c in RUN_DATA_COLS if c in d.columns]]
        d["filename"] = os.path.basename(f)
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=RUN_DATA_COLS + ["filename"])
    return pd.concat(frames, ignore_index=True, sort=False)


# ChannelData exports are huge (~2 GB per overnight run); only these columns are used.
CHANNEL_COLS = {"ChannelID", "RunIDRecord", "TimeStamp", "Timestamp", "ViableChannel",
                "TotalEventRate", "Baseline", "SignalRMS", "LevelOne",
                "Samples", "MinuteInBlock"}  # last two only in metric_avg_comparisons/export_run_metrics_avg.bat exports
CHANNEL_FLOAT32 = ["TotalEventRate", "Baseline", "SignalRMS", "LevelOne"]


def read_channel_data(files, per_minute=False):
    """per_minute=True keeps one row per channel per minute of run time (the same rows the
    overnight figures use), dropping the rest file by file so memory stays low."""
    frames = []
    for f in files:
        d = pd.read_csv(f, low_memory=False, usecols=lambda c: c in CHANNEL_COLS)
        n_read = len(d)
        ts_col = "TimeStamp" if "TimeStamp" in d.columns else "Timestamp"
        # (an averaged export, with its Samples column, is already one row per channel per minute)
        if (per_minute and "Samples" not in d.columns and ts_col in d.columns
                and pd.api.types.is_numeric_dtype(d[ts_col])):
            secs = d[ts_col].astype(float)
            d = d[np.round(secs - secs.min(), 0) % 60 == 0]  # matches Time_sec in the markup
        for c in CHANNEL_FLOAT32:
            if c in d.columns:
                d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
        if "ChannelID" in d.columns:
            d["ChannelID"] = pd.to_numeric(d["ChannelID"], downcast="integer")
        d["filename"] = os.path.basename(f)
        frames.append(d)
        kept = f" (kept {len(d):,}, one per minute)" if len(d) != n_read else ""
        print(f"Read {os.path.basename(f)}: {n_read:,} rows{kept}")
    if not frames:
        return pd.DataFrame(columns=["filename"])
    out = pd.concat(frames, ignore_index=True, sort=False)
    del frames
    out["filename"] = out["filename"].astype("category")
    return out


def per_minute_rows(channel_data):
    """The ChannelData rows the overnight figures use: one snapshot per whole minute of run time,
    or every row of an averaged export (metric_avg_comparisons/export_run_metrics_avg.bat), which is
    already per minute."""
    if "Samples" in channel_data.columns:
        return channel_data
    return channel_data[channel_data["Time_sec"] % 60 == 0]


def align_to_system_clock(sys_d, ch_d):
    """Put a run's ChannelData on its SystemMetrics clock (time 0 = first SystemMetrics reading).
    Identical for full/snapshot exports; matters if an averaged export skipped the first minute."""
    t0 = sys_d["Time_abs_sec"].min()
    ch_d = ch_d.copy()
    t = ch_d["Time_abs_sec"] - t0
    ch_d["Time"], ch_d["Time_minutes"], ch_d["Time_sec"] = t / 3600, t / 60, np.round(t, 0)
    return ch_d


def read_experiment(experiment_dir, channel_per_minute=False):
    system_metrics = concat_csv_files(list_files(experiment_dir, "SystemMetrics"))
    channel_data = read_channel_data(list_files(experiment_dir, "ChannelData"), per_minute=channel_per_minute)
    run_data = read_run_data(list_files(experiment_dir, "RunData"))
    system_metrics = run_metrics_metadata_markup(system_metrics)
    channel_data = run_metrics_metadata_markup(channel_data)
    return system_metrics, channel_data, run_data


# %% Overnight (single-run) report - figure
# --------------------------------------------------------------------------------------------------
# Overnight (single-run) version
# --------------------------------------------------------------------------------------------------

def _style_overnight(ax, xlabel, ylabel):
    """theme_minimal() + the final `&` theme() overrides in the R layout."""
    ax.set_xlabel(xlabel, fontsize=8, color="black")
    ax.set_ylabel(ylabel, fontsize=8, color="black")
    ax.tick_params(labelsize=7, colors="black", length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.minorticks_on()
    ax.tick_params(which="minor", length=0)
    ax.grid(True, which="major", color="#EBEBEB", linewidth=0.6)
    ax.grid(True, which="minor", color="#EBEBEB", linewidth=0.3)
    ax.set_axisbelow(True)


def _set_minor_midpoints(ax):
    for axis in (ax.xaxis, ax.yaxis):
        ticks = axis.get_majorticklocs()
        if len(ticks) > 1:
            axis.set_minor_locator(matplotlib.ticker.FixedLocator((ticks[:-1] + ticks[1:]) / 2))


PT = dict(s=0.4, linewidths=0, rasterized=True)  # ~ ggplot geom_point(size=0.001)


def _draw_run_table(ax, table, protocol_cols, avg_cols, avg_label="Average Values for Full Run"):
    """gt table with two coloured column spanners, drawn with matplotlib."""
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    cols = list(table.columns)
    headers = [textwrap.fill(c, 16) for c in cols]
    rows = [[fmt_value(v) for v in r] for r in table.itertuples(index=False)]
    fs = 10
    fig = ax.figure
    renderer = fig.canvas.get_renderer()
    ax_w = ax.get_window_extent(renderer).width

    def text_w(t, size):
        tt = fig.text(0, 0, t, fontsize=size, linespacing=1.1)
        w = tt.get_window_extent(renderer).width
        tt.remove()
        return w

    for _ in range(6):  # shrink the font until the table fits the figure width
        widths = [max([text_w(h, fs)] + [text_w(r[i], fs) for r in rows]) + 1.2 * fs * fig.dpi / 72
                  for i, h in enumerate(headers)]
        if sum(widths) <= ax_w:
            break
        fs *= 0.9
    x = np.concatenate([[0], np.cumsum(widths)]) / ax_w
    x = x + (1 - x[-1]) / 2  # centre the table

    n_rows = len(rows)
    h_span, h_head, h_row = 0.28, 0.42, 0.30 / max(n_rows, 1)
    y_span_top, y_head_top = 1.0, 1.0 - h_span
    y_body_top = y_head_top - h_head

    def span(label, names, color):
        idx = [cols.index(c) for c in names if c in cols]
        if not idx:
            return
        x0, x1 = x[min(idx)], x[max(idx) + 1]
        ax.add_patch(Rectangle((x0, y_head_top), x1 - x0, h_span, color=color, lw=0))
        ax.text((x0 + x1) / 2, y_head_top + h_span / 2, label, ha="center", va="center", fontsize=fs)

    span("Protocol Settings", protocol_cols, "lightblue")
    span(avg_label, avg_cols, "lightgreen")
    for i, h in enumerate(headers):
        ax.text((x[i] + x[i + 1]) / 2, y_body_top + h_head / 2, h, ha="center", va="center",
                fontsize=fs, linespacing=1.1)
        for r, row in enumerate(rows):
            ax.text((x[i] + x[i + 1]) / 2, y_body_top - (r + 0.5) * h_row, row[i],
                    ha="center", va="center", fontsize=fs)
    for yy, lw in [(y_span_top, 1.5), (y_head_top, 0.6), (y_body_top, 1.2),
                   (y_body_top - n_rows * h_row, 1.5)]:
        ax.plot([x[0], x[-1]], [yy, yy], color="#D3D3D3", lw=lw, clip_on=False)


def _hr_breaks(max_hr, step):
    """Axis breaks every `step` hours, widened (x2) for long time spans so labels don't collide."""
    while max_hr / step > 24:
        step *= 2
    return seq(0, max_hr, step)


class TimeMap:
    """Shortens long gaps between runs on the time axis. Data are plotted at display time
    disp(t); tick labels show real time t. gaps = [(start_hr, end_hr), ...] in real hours."""

    def __init__(self, gaps, width=GAP_BRIDGE_WIDTH_HR):
        self.gaps = sorted(gaps)
        self.width = width

    def disp(self, t):
        t = np.asarray(t, dtype=float)
        out = t.copy()
        for g0, g1 in self.gaps:
            inside = (t > g0) & (t < g1)
            out = np.where(inside, out - (t - g0) + (t - g0) / (g1 - g0) * self.width, out)
            out = np.where(t >= g1, out - (g1 - g0 - self.width), out)
        return out

    def real(self, d):
        d = float(d)
        for g0, g1 in self.gaps:
            g0_d = float(self.disp(g0))
            if d >= g0_d + self.width:
                d += (g1 - g0 - self.width)
            elif d > g0_d:
                d = g0 + (d - g0_d) / self.width * (g1 - g0)
        return d

    def in_gap(self, t):
        return any(g0 < t < g1 for g0, g1 in self.gaps)

    def bands(self):  # (display start, display end, real gap length) of each bridge
        return [(float(self.disp(g0)), float(self.disp(g0)) + self.width, g1 - g0)
                for g0, g1 in self.gaps]


def _run_averages(sys_d, ch_d):
    """The "Average Values" columns of the run table, for one run."""
    viable = is_viable(ch_d["ViableChannel"])
    lvl1_clean = ch_d["LevelOne"].where(viable & (ch_d["LevelOne"] != LEVEL_ONE_SENTINEL))
    return {
        "Total Event Rate": round(float(np.nanmean(sys_d["TotalEventRate"].astype(float)))),
        "Channel Activity (%)": round(100 * viable.sum() / len(ch_d)),
        "Active Channel Count": round(float(np.nanmean(sys_d["ActiveChannelCount"].astype(float)))),
        "Baseline (mV)": round(float(np.nanmean(ch_d["Baseline"].where(viable)))),
        "Level 1 (uV)": round(float(np.nanmean(lvl1_clean))),
        "Signal RMS": round(float(np.nanmean(ch_d["SignalRMS"].where(viable))), 4),
        "Current (uA)": round(float(np.nanmean(sys_d["Current(A)"].astype(float) * 1e6))),
        "Bias Voltage (V)": round(float(np.nanmean(sys_d["BiasVoltage(V)"].astype(float))), 1),
    }


AVG_COLS = ["Total Event Rate", "Channel Activity (%)", "Active Channel Count", "Baseline (mV)",
            "Level 1 (uV)", "Signal RMS", "Current (uA)", "Bias Voltage (V)"]


def _run_table(run_ids, sys_d, ch_d, run_data, protocol_settings):
    """One table row per run: RunData metadata (+ protocol settings) and that run's averages."""
    rd = run_data.loc[run_data["SampleID"].isin(run_ids),
                      [c for c in RUN_DATA_COLS if c in run_data.columns]]
    rd = rd.drop_duplicates("SampleID")
    if protocol_settings is not None:
        rd = rd.merge(protocol_settings, on=["ProtocolName", "SettingsGroup"], how="left")
    setting_cols = [c for c in ["Target Baseline (mV)", "Target Bias (V)", "Applied Pressure (psi)"]
                    if c in rd.columns and rd[c].notna().any()]  # pivot_longer/drop_na/pivot_wider
    rd = rd.rename(columns={"SampleID": "Sample ID", "ProtocolName": "Protocol",
                            "SettingsGroup": "Settings", "ReagentLot": "Reagent Lot",
                            "DetectorLotNumber": "Lot", "DetectorWaferID": "Wafer",
                            "DetectorDieNumber": "Die"})
    detector_cols = [c for c in ["Lot", "Wafer", "Die"] if c in rd.columns]  # from RunData Detector* columns
    sample_cols = ["Sample ID", "Protocol", "Settings"] + setting_cols + detector_cols + ["Reagent Lot"]
    for c in sample_cols:
        if c not in rd.columns:
            rd[c] = None
    rd = rd.set_index("Sample ID")
    rows = []
    for rid in run_ids:  # keep run order; runs missing from RunData still get a row
        row = {c: (rd.at[rid, c] if rid in rd.index else None) for c in sample_cols[1:]}
        row = {"Sample ID": rid, **row,
               **_run_averages(sys_d[sys_d["RunID"] == rid], ch_d[ch_d["RunID"] == rid])}
        rows.append(row)
    return pd.DataFrame(rows, columns=sample_cols + AVG_COLS), sample_cols


def _overnight_run_figure(run_ids, sys_d, ch_d, run_data, protocol_settings, run_starts=None,
                          xmap=None):
    """The overnight figure. `run_ids` is one run ID (overnight mode) or several runs already on a
    shared clock (sequential mode); `run_starts` = [(start_hr, label), ...] marks each run's start.
    `xmap` (a TimeMap) means Time is already in display units with long gaps shortened."""
    if isinstance(run_ids, str):
        run_ids = [run_ids]
    multi = len(run_ids) > 1
    rng = np.random.default_rng(1)
    max_sys = sys_d["Time"].max()
    max_ch = ch_d["Time"].max()
    viable = is_viable(ch_d["ViableChannel"])
    chv = ch_d[viable]
    XL = "Run Time (hrs)" if xmap is None or not xmap.gaps else \
        f"Run Time (hrs; gaps > {GAP_BRIDGE_MIN_HR:g} h shortened)"

    def set_x(a, max_disp, step):
        if xmap is None or not xmap.gaps:
            set_scale(a, "x", 0, max_disp, _hr_breaks(max_disp, step))
            return
        br = [b for b in _hr_breaks(xmap.real(max_disp), step) if not xmap.in_gap(b)]
        set_scale(a, "x", 0, max_disp, xmap.disp(br))
        a.set_xticklabels([fmt_value(float(b)) for b in br])

    table, sample_cols = _run_table(run_ids, sys_d, ch_d, run_data, protocol_settings)
    tbl_h = 0.42 + 0.10 * (len(table) - 1)  # taller table band for more rows
    fig = plt.figure(figsize=(16.5, 9 + 1.3 * (tbl_h - 0.42)))
    gs = fig.add_gridspec(4, 3, height_ratios=[tbl_h, 1, 1, 1], hspace=0.45, wspace=0.22,
                          left=0.04, right=0.96, top=0.97, bottom=0.06)
    ax_tbl = fig.add_subplot(gs[0, :])
    ax = {name: fig.add_subplot(gs[r, c]) for name, (r, c) in {
        "TER": (1, 0), "B": (1, 1), "Cu": (1, 2),
        "TERsys": (2, 0), "CER": (2, 1), "LVL1": (2, 2),
        "E": (3, 0), "RMS": (3, 1), "Base": (3, 2)}.items()}

    # ---- panels from SystemMetrics ----
    def sys_scatter(a, col, color, ylab, lo, hi, by):
        d = sys_d[within(sys_d[col], lo, hi)]
        a.scatter(d["Time"], d[col], color=color, **PT)
        set_x(a, max_sys, 2)
        set_scale(a, "y", lo, hi, seq(lo, hi, by))
        _style_overnight(a, XL, ylab)

    sys_scatter(ax["TERsys"], "TotalEventRate", "hotpink", "Total Event Rate (system)", 0, 800, 200)
    sys_scatter(ax["E"], "ActiveChannelCount", R_GREEN, "Active Channel Count", 0, 260, 50)
    # (the R script also builds a Bias Voltage panel `V` that is not used in the layout)

    a = ax["Cu"]
    cur = sys_d["Current(A)"].astype(float) * 1e6
    bias_scaled = (sys_d["BiasVoltage(V)"].astype(float) + 5 / 3) * 30
    m = within(cur, 50, 200)
    a.scatter(sys_d["Time"][m], cur[m], color="darkblue", **PT)
    m = within(bias_scaled, 50, 200)
    a.scatter(sys_d["Time"][m], bias_scaled[m], color="orange", **PT)
    set_x(a, max_sys, 2)
    set_scale(a, "y", 50, 200, seq(50, 200, 25))
    sec = a.secondary_yaxis("right", functions=(lambda y: y / 30 - 5 / 3, lambda v: (v + 5 / 3) * 30))
    sec.set_ylabel("Bias Voltage (V)", fontsize=8, color="black")
    sec.tick_params(labelsize=7, colors="black", length=0)
    for sp in sec.spines.values():
        sp.set_visible(False)
    a.scatter([0.25 * max_sys], [200], color="darkblue", s=12, zorder=3)
    a.text(0.26 * max_sys, 200, "Current (uA)", ha="left", va="center", fontsize=8)
    a.scatter([0.5 * max_sys], [200], color="orange", s=12, zorder=3)
    a.text(0.51 * max_sys, 200, "Bias Voltage (V)", ha="left", va="center", fontsize=8)
    _style_overnight(a, XL, "Current (uA)")

    norm_er = sys_d.assign(TotalEventRate_norm=sys_d["TotalEventRate"].astype(float)
                           / sys_d["ActiveChannelCount"].astype(float))

    # ---- panels from ChannelData ----
    a = ax["TER"]
    d = chv[within(chv["TotalEventRate"], 0, 8)]
    ch_ids = np.sort(ch_d["ChannelID"].unique())
    pal = dict(zip(ch_ids, hue_pal(len(ch_ids))))
    a.scatter(d["Time"], d["TotalEventRate"], c=d["ChannelID"].map(pal).tolist(), **PT)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 0, 8, seq(0, 8, 1))
    _style_overnight(a, XL, "Total Event Rate (channel)")

    a = ax["CER"]
    nd = norm_er[within(norm_er["TotalEventRate_norm"], 0, 6) & (norm_er["Time"] <= max_ch)]
    a.scatter(nd["Time"], nd["TotalEventRate_norm"], color=R_GRAY, **PT)
    bins = pd.cut(chv["ChannelID"].astype(float), bins=5)  # cut(ChannelID, breaks=5)
    bin_cols = hue_pal(5)
    d = chv.assign(x_bins=bins)
    d = d[within(d["TotalEventRate"], 0, 6)]  # scale limits remove points before smoothing
    for i, cat in enumerate(bins.cat.categories):
        g = d[d["x_bins"] == cat]
        for _, gr in g.groupby("RunID", observed=True):  # smooth each run separately (no line across gaps)
            xs, ys = lowess_smooth(gr["Time"], gr["TotalEventRate"])
            a.plot(xs, ys, color=bin_cols[i], lw=1)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 0, 6, seq(0, 6, 1))
    a.scatter([0], [6], color=R_GRAY, s=6, zorder=3)
    # legend positions scale with this panel's own x range (max_ch; the R code used max_sys,
    # which is the same value whenever SystemMetrics and ChannelData cover the same span)
    a.text(0.01 * max_ch, 6, "Total event rate / Active channel count", ha="left", va="center", fontsize=8)
    for i, lab in enumerate(["Ch1-51", "52-102", "103-153", "154-204", "205-256"]):
        xp = (0.5 + 0.1 * i) * max_ch
        a.scatter([xp], [6], color=bin_cols[i], s=6, marker="s", zorder=3)
        a.text(xp + 0.01 * max_ch, 6, lab, ha="left", va="center", fontsize=6.3)
    _style_overnight(a, XL, "Total Event Rate")

    a = ax["B"]
    d = ch_d[within(ch_d["ChannelID"], 0, 260)]
    v = is_viable(d["ViableChannel"])
    a.scatter(d["Time"][~v], d["ChannelID"][~v], color="red", **PT)
    a.scatter(d["Time"][v], d["ChannelID"][v], color=R_GREEN, **PT)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 0, 260, seq(0, 260, 50))
    _style_overnight(a, XL, "Channel Viability")

    a = ax["Base"]
    base_mean = chv.groupby("Time", as_index=False)["Baseline"].mean()
    d = chv[within(chv["Baseline"], 500, 2500)]
    a.scatter(d["Time"], d["Baseline"], color="deepskyblue", **PT)
    bm = base_mean[within(base_mean["Baseline"], 500, 2500)]
    a.scatter(bm["Time"], bm["Baseline"], color="black", **PT)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 500, 2500, seq(500, 2500, 500))
    _style_overnight(a, XL, "Baseline (mV)")

    a = ax["RMS"]
    d = chv[chv["SignalRMS"] < 0.08].copy()  # should check why this threshold value
    d["Mean"] = d.groupby("Time")["SignalRMS"].transform("mean")
    a.scatter(jitter(d["Time"], rng), jitter(d["SignalRMS"], rng), color="#79CDCD", **PT)  # darkslategray3
    mm = d.drop_duplicates("Time")
    a.scatter(mm["Time"], mm["Mean"], color="black", **PT)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 0, 0.08)
    _style_overnight(a, XL, "Signal RMS")

    a = ax["LVL1"]
    d = chv[chv["LevelOne"] != LEVEL_ONE_SENTINEL].copy()
    d["Mean"] = d.groupby("Time")["LevelOne"].transform("mean")
    jx, jy = jitter(d["Time"], rng), jitter(d["LevelOne"], rng)
    m = (jy >= 300) & (jy <= 1500)
    a.scatter(jx[m], jy[m], color="orange", **PT)
    mm = d.drop_duplicates("Time")
    mm = mm[within(mm["Mean"], 300, 1500)]
    a.scatter(mm["Time"], mm["Mean"], color="black", s=3, linewidths=0, rasterized=True)
    set_x(a, max_ch, 1)
    set_scale(a, "y", 300, 1500)
    _style_overnight(a, XL, "Level 1 (uV)")

    for a in ax.values():
        _set_minor_midpoints(a)

    # ---- sequential mode: mark where each injection starts ----
    if multi and run_starts:
        from matplotlib.transforms import blended_transform_factory
        for a in ax.values():
            tr = blended_transform_factory(a.transData, a.transAxes)
            for k, (t_hr, label) in enumerate(run_starts):
                if k > 0:
                    a.axvline(t_hr, color="#555555", lw=0.6, ls="--", zorder=0.5)
                a.text(t_hr, 1.01, label, transform=tr, ha="left", va="bottom",
                       fontsize=7, color="#555555", clip_on=False)

    # ---- sequential mode: shortened gaps drawn as a shaded bridge ----
    if xmap is not None:
        for a in ax.values():
            for x0, x1, gap_hr in xmap.bands():
                a.axvspan(x0, x1, color="#EDEDED", lw=0, zorder=0.4)
                a.text((x0 + x1) / 2, 0.5, f"{gap_hr:.1f} h gap", transform=a.get_xaxis_transform(),
                       rotation=90, ha="center", va="center", fontsize=6, color="#777777")

    span_label = "Average Values per Injection" if multi else "Average Values for Full Run"
    _draw_run_table(ax_tbl, table, sample_cols[1:], AVG_COLS, avg_label=span_label)
    return fig


def _protocol_settings_or_none(use_protocol_sheet):
    if not use_protocol_sheet:
        return None
    try:
        return build_protocol_settings_df()
    except Exception as e:  # e.g. no gspread credentials.json on this PC, or no network
        print(f"WARNING: skipping Google Sheets protocol lookup ({type(e).__name__}: {e}).\n"
              "         The table will omit Target Baseline / Target Bias / Applied Pressure. "
              "Set USE_PROTOCOL_SHEET = False to silence this.")
        return None


def _save(fig, path):
    fig.savefig(path, dpi=JPG_DPI)
    show_figure(fig)
    plt.close(fig)
    print("Saved", path)
    return path


# %% Overnight (single-run) report - driver
def overnight_run_plots(experiment_dir=None, out_dir=None, use_protocol_sheet=True):
    experiment_dirs = as_dir_list(experiment_dir)
    protocol_settings = _protocol_settings_or_none(use_protocol_sheet)
    stamp = datetime.now().strftime("_%Y%m%d_%H%M%S")
    base = output_prefix(experiment_dirs, out_dir)
    run_ids = find_run_ids(experiment_dirs)

    # ChannelData: one row per minute of run time (a snapshot, not a rolling average)
    system_metrics, channel_data, run_data = read_experiment(experiment_dirs, channel_per_minute=True)
    channel_data = per_minute_rows(channel_data)

    saved = []
    for run_id in run_ids:
        sys_d = system_metrics[system_metrics["RunID"] == run_id]
        ch_d = channel_data[channel_data["RunID"] == run_id]
        if sys_d.empty or ch_d.empty:
            print(f"Skipping {run_id}: missing SystemMetrics or ChannelData")
            continue
        ch_d = align_to_system_clock(sys_d, ch_d)
        fig = _overnight_run_figure(run_id, sys_d, ch_d, run_data, protocol_settings)
        saved.append(_save(fig, os.path.join(base, f"{run_id}_overnight_instrument_metrics{stamp}.jpg")))
    return saved


# %% Sequential report (injections on one detector appended end to end) - driver
def sequential_run_plots(experiment_dir=None, out_dir=None, use_protocol_sheet=True):
    """Overnight-style figure per detector (wafer-die) with all of its injections on one clock:
    time 0 = start of the earliest run; later runs keep their real start time, so gaps between
    injections show as gaps on the x axis."""
    experiment_dirs = as_dir_list(experiment_dir)
    protocol_settings = _protocol_settings_or_none(use_protocol_sheet)
    stamp = datetime.now().strftime("_%Y%m%d_%H%M%S")
    base = output_prefix(experiment_dirs, out_dir)

    system_metrics, channel_data, run_data = read_experiment(experiment_dirs, channel_per_minute=True)

    saved = []
    for wd in sorted(unique_in_order(system_metrics["WaferDie"])):
        sys_d = system_metrics[system_metrics["WaferDie"] == wd].copy()
        ch_d = channel_data[channel_data["WaferDie"] == wd].copy()
        if sys_d.empty or ch_d.empty:
            print(f"Skipping {wd}: missing SystemMetrics or ChannelData")
            continue
        # order runs by their real start time
        starts = sys_d.groupby("RunID", observed=True)["Time_abs_sec"].min().sort_values()
        run_ids = [r for r in starts.index if (ch_d["RunID"] == r).any()]
        missing = [r for r in starts.index if r not in run_ids]
        if missing:
            print(f"NOTE: {', '.join(missing)} has no ChannelData; left out of the {wd} figure.")
        sys_d = sys_d[sys_d["RunID"].isin(run_ids)]
        ch_d = ch_d[ch_d["RunID"].isin(run_ids)]

        # shared clock: everything relative to the earliest timestamp on this detector
        t0 = min(sys_d["Time_abs_sec"].min(), ch_d["Time_abs_sec"].min())
        for d in (sys_d, ch_d):
            t = d["Time_abs_sec"] - t0
            d["Time"] = t / 3600
            d["Time_minutes"] = t / 60
            d["Time_sec"] = np.round(t, 0)

        inj = sys_d.groupby("RunID", observed=True)["Injection"].first()
        run_starts = [((starts[r] - t0) / 3600, str(inj.get(r, r))) for r in run_ids]
        # gaps between consecutive runs (end of everything so far -> start of the next run)
        ends = pd.concat([sys_d.groupby("RunID", observed=True)["Time"].max(),
                          ch_d.groupby("RunID", observed=True)["Time"].max()], axis=1).max(axis=1)
        gaps, last_end = [], ends[run_ids[0]]
        for k in range(1, len(run_ids)):
            gaps.append((last_end, run_starts[k][0]))
            last_end = max(last_end, ends[run_ids[k]])
        print(f"{wd}: {len(run_ids)} run(s) " + ", ".join(f"{lab} @ {t:.1f} h" for t, lab in run_starts)
              + ("" if not gaps else "; gaps " + ", ".join(f"{g1 - g0:.1f} h" for g0, g1 in gaps)))

        # shorten long gaps on the time axis (tick labels keep the real run time)
        xmap = TimeMap([(g0, g1) for g0, g1 in gaps if g1 - g0 > GAP_BRIDGE_MIN_HR])
        if xmap.gaps:
            for d in (sys_d, ch_d):
                d["Time"] = xmap.disp(d["Time"].to_numpy())
            run_starts = [(float(xmap.disp(t)), lab) for t, lab in run_starts]

        fig = _overnight_run_figure(run_ids, sys_d, ch_d, run_data, protocol_settings, run_starts, xmap)
        stem = os.path.commonprefix(run_ids) if len(run_ids) > 1 else run_ids[0]
        labels = "+".join(lab for _, lab in run_starts) if len(run_ids) > 1 else ""
        name = f"{stem}{labels}_sequential_instrument_metrics{stamp}.jpg".replace(os.sep, "_")
        saved.append(_save(fig, os.path.join(base, name)))
    return saved


# %% Overlay report - helpers
# --------------------------------------------------------------------------------------------------
# Overlay version
# --------------------------------------------------------------------------------------------------

def _style_overlay(ax):
    """theme_light() + the final `&` theme() overrides."""
    ax.tick_params(labelsize=10, colors="black", length=3, width=0.5, color="#B3B3B3")
    for sp in ax.spines.values():
        sp.set_color("#B3B3B3")
        sp.set_linewidth(0.6)
    ax.grid(True, color="#DEDEDE", linewidth=0.5)
    ax.set_axisbelow(True)


def _facet_lines(subfig, df, x, y, facets, colors, group="Injection", ylabel="", xlabel="",
                 ylim=None, ybreaks=None):
    """ggplot(aes(x, y, color=Injection)) + geom_line(aes(group=...)) + facet_wrap(~WaferDie)."""
    nrow, ncol = wrap_dims(len(facets))
    axes = subfig.subplots(nrow, ncol, sharex=True, sharey=True, squeeze=False)
    for k, a in enumerate(axes.flat):
        if k >= len(facets):
            a.set_visible(False)
            continue
        wd = facets[k]
        d = df[df["WaferDie"] == wd]
        for g, gd in d.groupby(group, sort=True, observed=True):
            gd = gd.sort_values(x)
            inj = gd["Injection"].iloc[0]
            a.plot(gd[x], gd[y], color=colors.get(inj, "gray"), lw=0.7)
        a.set_title(wd, fontsize=11, color="black", pad=3)
        _style_overlay(a)
        if ylim is not None:
            set_scale(a, "y", ylim[0], ylim[1], ybreaks)
    # bottom-row axes that sit above a hidden facet still need tick labels
    for k, a in enumerate(axes.flat):
        if k < len(facets) and k + ncol >= len(facets):
            a.tick_params(labelbottom=True)
    subfig.subplots_adjust(left=0.24, right=0.97, bottom=0.2, top=0.87, wspace=0.12, hspace=0.35)
    subfig.supxlabel(xlabel, fontsize=11, y=0.01)
    subfig.supylabel(ylabel, fontsize=11, x=0.01)


# %% Overlay report - driver
def overlay_run_plots(experiment_dir=None, out_dir=None):
    experiment_dir = as_dir_list(experiment_dir)
    stamp = datetime.now().strftime("_%Y%m%d_%H%M%S")
    base = output_prefix(experiment_dir, out_dir)

    sm, cd, _run_data = read_experiment(experiment_dir)

    facets = sorted(unique_in_order(sm["WaferDie"]))
    injections = sorted(set(unique_in_order(sm["Injection"])) | set(unique_in_order(cd["Injection"])))
    colors = dict(zip(injections, hue_pal(len(injections))))

    # ---- SystemMetrics panels ----
    ters = sm.copy()
    ters["Mean"] = ters.groupby(["Time_sec", "RunIDRecord"])["TotalEventRate"].transform("mean")
    sm_norm = sm.assign(TotalEventRate_norm=sm["TotalEventRate"].astype(float)
                        / sm["ActiveChannelCount"].astype(float))
    sm_cu = sm.assign(**{"Current(A)": sm["Current(A)"].astype(float) * 1e6})
    sm_res = sm.assign(**{"Resistance (kOhms)": sm["Resistance(Ohms)"].astype(float) / 1000})

    # ---- ChannelData panels ----
    # Each panel plots the across-channel mean at each time point. Computed with groupby
    # aggregation (one row per time point) rather than transform + drop_duplicates on a full copy
    # of ChannelData, which needs far too much memory for multi-GB overnight exports.
    keys = ["WaferDie", "Injection", "InjectionSample"]
    cdv = cd[is_viable(cd["ViableChannel"])]

    def mean_by_time(d, value):  # mean per (Time_sec, RunIDRecord), as in the R code
        g = d.groupby(keys + ["RunIDRecord", "Time_sec"], observed=True)
        out = g.agg(Mean=(value, "mean"), Time_minutes=("Time_minutes", "first")).reset_index()
        return out

    base_df = mean_by_time(cdv, "Baseline")
    rms_df = mean_by_time(cdv[cdv["SignalRMS"] < 0.1], "SignalRMS")
    rms_df = rms_df[within(rms_df["Mean"], 0, 0.07)]
    lvl = cdv[cdv["LevelOne"] != LEVEL_ONE_SENTINEL]
    # NB: the R code groups LVL1 by `Time` only (not Time_sec + RunIDRecord like the others),
    # so runs whose timestamps line up get averaged together. Kept as-is to match.
    lvl_mean = lvl.groupby("Time")["LevelOne"].mean()
    lvl_df = (lvl.groupby(keys + ["Time"], observed=True)["Time_minutes"].first().reset_index())
    lvl_df["Mean"] = lvl_df["Time"].map(lvl_mean)
    del cdv, lvl

    def thin(d, grp):  # many identical (x, Mean) rows per channel -> plot each once
        return d.drop_duplicates(["WaferDie", grp, "Injection", "Time_minutes", "Mean"])

    fig = plt.figure(figsize=(14, 8))
    band, body = fig.subfigures(2, 1, height_ratios=[0.07, 1])
    outer = body.subfigures(1, 4, wspace=0.0, width_ratios=[1, 1, 1, 0.9])
    cols = [outer[i].subfigures(3, 1, hspace=0.0) if i < 3 else None for i in range(4)]
    mins = "Run Time (mins)"

    panels = [
        (cols[0][0], thin(ters, "Injection"), "Mean", "Systemwide Total Event Rate", "Injection", mins, None),
        (cols[0][1], thin(base_df, "Injection"), "Mean", "Baseline (mV)", "Injection", mins, None),
        (cols[0][2], sm, "BiasVoltage(V)", "Bias Voltage (V)", "Injection", mins, None),
        (cols[1][0], sm, "ActiveChannelCount", "Active Channel Count", "Injection", mins, (0, 260, seq(0, 260, 50))),
        (cols[1][1], thin(rms_df, "InjectionSample"), "Mean", "Signal RMS", "InjectionSample", mins,
         (0, 0.07, seq(0, 0.07, 0.02))),
        (cols[1][2], sm_cu, "Current(A)", "Current (A)", "Injection", mins, None),  # label as in R (values are uA)
        (cols[2][0], sm_norm, "TotalEventRate_norm", "Systemwide Event Rate /\nActive Channel Count",
         "Injection", mins, None),
        (cols[2][1], thin(lvl_df, "InjectionSample"), "Mean", "Level 1", "InjectionSample", "Run Time (min)", None),
        (cols[2][2], sm_res, "Resistance (kOhms)", "Resistance (kOhms)", "Injection", mins, None),
    ]
    for sf, d, y, ylab, grp, xlab, ylim in panels:
        if ylim is not None:
            _facet_lines(sf, d, "Time_minutes", y, facets, colors, group=grp, ylabel=ylab, xlabel=xlab,
                         ylim=ylim[:2], ybreaks=ylim[2])
        else:
            _facet_lines(sf, d, "Time_minutes", y, facets, colors, group=grp, ylabel=ylab, xlabel=xlab)

    # ---- Channel viability: facet_grid(Injection ~ WaferDie, scales="free_x") ----
    sf = outer[3]
    inj_rows = sorted(unique_in_order(cd["Injection"]))
    cd_facets = sorted(unique_in_order(cd["WaferDie"]))
    axes = sf.subplots(len(inj_rows), len(cd_facets), sharey=True, sharex="col", squeeze=False)
    # one reading per channel per minute (as in the overnight report); plotting every second
    # (tens of millions of points for overnight runs) looks the same but is very slow
    cdb = cd[within(cd["ChannelID"], 0, 260) & (cd["Time_sec"] % 60 == 0)]
    viable = is_viable(cdb["ViableChannel"])
    for i, inj in enumerate(inj_rows):
        for j, wd in enumerate(cd_facets):
            a = axes[i, j]
            m = (cdb["Injection"] == inj) & (cdb["WaferDie"] == wd)
            for flag, col in [(False, "red"), (True, R_GREEN)]:
                d = cdb[m & (viable == flag)]
                a.scatter(d["Time_minutes"], d["ChannelID"], color=col, s=0.3, linewidths=0, rasterized=True)
            set_scale(a, "y", 0, 260, seq(0, 260, 50))
            _style_overlay(a)
            if i == 0:
                a.set_title(wd, fontsize=11, color="black", pad=3)
            if j == len(cd_facets) - 1:
                a.yaxis.set_label_position("right")
                a.set_ylabel(inj, fontsize=11, rotation=270, labelpad=12)
    sf.subplots_adjust(left=0.2, right=0.9, bottom=0.067, top=0.957, wspace=0.12, hspace=0.25)
    sf.supxlabel(mins, fontsize=11, y=0.003)
    sf.supylabel("Channel Viability", fontsize=11, x=0.01)

    # ---- collected legends at top ----
    inj_handles = [Line2D([], [], color=colors[i], lw=1.5, label=i) for i in injections]
    via_handles = [Line2D([], [], color=c, marker="o", ls="", label=l)
                   for c, l in [("red", "FALSE"), (R_GREEN, "TRUE")]]
    band.legend(handles=inj_handles, title="Injection", loc="center", bbox_to_anchor=(0.4, 0.5),
               ncol=len(inj_handles), fontsize=12, title_fontsize=12, frameon=False)
    band.legend(handles=via_handles, title="ViableChannel", loc="center", bbox_to_anchor=(0.8, 0.5),
               ncol=2, fontsize=12, title_fontsize=12, frameon=False)
    # format_delim(batch_wafer_dies, "", eol="_") also writes the column header, hence "WaferDie_"
    save_name = "WaferDie_" + "".join(f"{wd}_" for wd in unique_in_order(sm["WaferDie"]))
    path = os.path.join(base, f"{save_name}overlay_instrument_metrics{stamp}.jpg")
    fig.savefig(path, dpi=JPG_DPI)
    show_figure(fig)
    plt.close(fig)
    print("Saved", path)
    return path


# %% Run
# (guarded so other scripts, e.g. metric_avg_comparisons/compare_overnight_exports.py, can import this file's functions
#  without generating figures; running cells in VS Code or `python instrument_run_metrics.py` still runs it)
if __name__ == "__main__":
    if MODE == "overnight":
        outputs = overnight_run_plots(EXPERIMENT_DIR, OUT_DIR, use_protocol_sheet=USE_PROTOCOL_SHEET)
    elif MODE == "sequential":
        outputs = sequential_run_plots(EXPERIMENT_DIR, OUT_DIR, use_protocol_sheet=USE_PROTOCOL_SHEET)
    elif MODE == "overlay":
        outputs = overlay_run_plots(EXPERIMENT_DIR, OUT_DIR)
    else:
        raise ValueError(f"Unknown MODE: {MODE!r}")
    print(outputs)

# %%
