"""
instrument_run_metrics.py
Python port of instrument_run_metrics.R

Two report types (same as the R version):
  * overnight_run_plots() - single-run version (e.g. 16 h data collection), per-channel data,
                            one JPG per run ID found in the chosen folder.
  * overlay_run_plots()   - overlay version (e.g. instrument audit, tag titration), system-wide
                            means for multiple injections onto the same detector, one JPG per folder.

Usage
  python instrument_run_metrics.py overnight            # opens a file picker; pick any file in the experiment folder
  python instrument_run_metrics.py overlay --dir "\\\\PROTON\\...\\20250429_tag_titration_human"
  python instrument_run_metrics.py overnight --out "C:\\some\\output\\folder"

Packages: pandas, numpy, matplotlib, statsmodels (geom_smooth equivalent), gspread (Google Sheets).
tkinter (file picker) ships with standard Python on Windows.
"""

import argparse
import os
import re
import textwrap
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # files are saved, never shown; avoids GUI backend issues
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

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
    return pd.concat(frames, ignore_index=True, sort=False)


def is_viable(s):
    """ViableChannel == "TRUE" regardless of whether pandas read it as bool or text."""
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


def output_prefix(experiment_dir, out_dir):
    base = out_dir or OUTPUT_BASE or experiment_dir
    os.makedirs(base, exist_ok=True)
    return base


def list_files(experiment_dir, pattern):
    """list.files(dir, pattern=..., full.names=TRUE) - regex on file names, sorted."""
    rx = re.compile(pattern)
    return sorted(os.path.join(experiment_dir, f) for f in os.listdir(experiment_dir)
                  if rx.search(f) and os.path.isfile(os.path.join(experiment_dir, f)))


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
    if "_" in run_id:
        injection = _first(r"[A-Za-z]_.*$", run_id)  # last letter before underscore to end
    else:
        injection = _first(r"[A-Za-z]$", run_id)     # last letter
    return dict(RunID=run_id, Sample=sample, Die=die, Wafer=wafer,
                Instrument=instrument, Injection=injection)


def run_metrics_metadata_markup(df):
    df = df.rename(columns={"TimeStamp": "Timestamp"})  # ChannelData uses TimeStamp

    meta = pd.DataFrame([dict(filename=f, **_parse_run_id(f)) for f in df["filename"].unique()])
    meta["InjectionSample"] = meta["Injection"].astype(str) + " " + meta["Sample"].astype(str)
    meta["WaferDie"] = meta["Wafer"].astype(str) + "-" + meta["Die"].astype(str)
    df = df.drop(columns=[c for c in meta.columns if c != "filename" and c in df.columns])
    df = df.merge(meta, on="filename", how="left")

    # Time fields, per file
    ts = df["Timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        secs = ts.astype(float)
    else:
        parsed = pd.to_datetime(ts, errors="coerce")
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert(None)
        secs = (parsed - pd.Timestamp("1970-01-01")).dt.total_seconds()
    t0 = secs.groupby(df["filename"]).transform("min")
    df["Time_min"] = t0
    time_sec = secs - t0
    df["Time_minutes"] = time_sec / 60
    df["Time"] = time_sec / 3600
    df["Time_sec"] = np.round(time_sec, 0)  # R round() is also round-half-to-even
    return df


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


# --------------------------------------------------------------------------------------------------
# Shared read-in
# --------------------------------------------------------------------------------------------------

def read_experiment(experiment_dir):
    system_metrics = concat_csv_files(list_files(experiment_dir, "SystemMetrics"))
    channel_data = concat_csv_files(list_files(experiment_dir, "ChannelData"))
    run_data = concat_csv_files(list_files(experiment_dir, "RunData"), dtype=str)
    system_metrics = run_metrics_metadata_markup(system_metrics)
    channel_data = run_metrics_metadata_markup(channel_data)
    return system_metrics, channel_data, run_data


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


def _draw_run_table(ax, table, protocol_cols, avg_cols):
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
    span("Average Values for Full Run", avg_cols, "lightgreen")
    for i, h in enumerate(headers):
        ax.text((x[i] + x[i + 1]) / 2, y_body_top + h_head / 2, h, ha="center", va="center",
                fontsize=fs, linespacing=1.1)
        for r, row in enumerate(rows):
            ax.text((x[i] + x[i + 1]) / 2, y_body_top - (r + 0.5) * h_row, row[i],
                    ha="center", va="center", fontsize=fs)
    for yy, lw in [(y_span_top, 1.5), (y_head_top, 0.6), (y_body_top, 1.2),
                   (y_body_top - n_rows * h_row, 1.5)]:
        ax.plot([x[0], x[-1]], [yy, yy], color="#D3D3D3", lw=lw, clip_on=False)


def _overnight_run_figure(run_id, sys_d, ch_d, run_data, protocol_settings):
    rng = np.random.default_rng(1)
    max_sys = sys_d["Time"].max()
    max_ch = ch_d["Time"].max()
    viable = is_viable(ch_d["ViableChannel"])
    chv = ch_d[viable]

    fig = plt.figure(figsize=(16.5, 9))
    gs = fig.add_gridspec(4, 3, height_ratios=[0.42, 1, 1, 1], hspace=0.45, wspace=0.22,
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
        set_scale(a, "x", 0, max_sys, seq(0, max_sys, 2))
        set_scale(a, "y", lo, hi, seq(lo, hi, by))
        _style_overnight(a, "Run Time (hrs)", ylab)

    sys_scatter(ax["TERsys"], "TotalEventRate", "hotpink", "Total Event Rate (system)", 0, 800, 200)
    sys_scatter(ax["E"], "ActiveChannelCount", "green", "Active Channel Count", 0, 260, 50)
    # (the R script also builds a Bias Voltage panel `V` that is not used in the layout)

    a = ax["Cu"]
    cur = sys_d["Current(A)"].astype(float) * 1e6
    bias_scaled = (sys_d["BiasVoltage(V)"].astype(float) + 5 / 3) * 30
    m = within(cur, 50, 200)
    a.scatter(sys_d["Time"][m], cur[m], color="darkblue", **PT)
    m = within(bias_scaled, 50, 200)
    a.scatter(sys_d["Time"][m], bias_scaled[m], color="orange", **PT)
    set_scale(a, "x", 0, max_sys, seq(0, max_sys, 2))
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
    _style_overnight(a, "Run Time (hrs)", "Current (uA)")

    norm_er = sys_d.assign(TotalEventRate_norm=sys_d["TotalEventRate"].astype(float)
                           / sys_d["ActiveChannelCount"].astype(float))

    sys_avgs = {
        "Current (uA)": round(np.nanmean(sys_d["Current(A)"].astype(float) * 1e6)),
        "Bias Voltage (V)": round(np.nanmean(sys_d["BiasVoltage(V)"].astype(float)), 1),
        "Active Channel Count": round(np.nanmean(sys_d["ActiveChannelCount"].astype(float))),
        "Total Event Rate": round(np.nanmean(sys_d["TotalEventRate"].astype(float))),
    }

    # ---- panels from ChannelData ----
    a = ax["TER"]
    d = chv[within(chv["TotalEventRate"], 0, 8)]
    ch_ids = np.sort(ch_d["ChannelID"].unique())
    pal = dict(zip(ch_ids, hue_pal(len(ch_ids))))
    a.scatter(d["Time"], d["TotalEventRate"], c=d["ChannelID"].map(pal).tolist(), **PT)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 0, 8, seq(0, 8, 1))
    _style_overnight(a, "Run Time (hrs)", "Total Event Rate (channel)")

    a = ax["CER"]
    nd = norm_er[within(norm_er["TotalEventRate_norm"], 0, 6) & (norm_er["Time"] <= max_ch)]
    a.scatter(nd["Time"], nd["TotalEventRate_norm"], color="gray", s=0.8, linewidths=0, rasterized=True)
    bins = pd.cut(chv["ChannelID"].astype(float), bins=5)  # cut(ChannelID, breaks=5)
    bin_cols = hue_pal(5)
    d = chv.assign(x_bins=bins)
    d = d[within(d["TotalEventRate"], 0, 6)]  # scale limits remove points before smoothing
    for i, cat in enumerate(bins.cat.categories):
        g = d[d["x_bins"] == cat]
        xs, ys = lowess_smooth(g["Time"], g["TotalEventRate"])
        a.plot(xs, ys, color=bin_cols[i], lw=1)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 0, 6, seq(0, 6, 1))
    a.scatter([0], [6], color="gray", s=6, zorder=3)
    a.text(0.01 * max_sys, 6, "Total event rate / Active channel count", ha="left", va="center", fontsize=8)
    for i, lab in enumerate(["Ch1-51", "52-102", "103-153", "154-204", "205-256"]):
        xp = (0.5 + 0.1 * i) * max_sys
        a.scatter([xp], [6], color=bin_cols[i], s=6, marker="s", zorder=3)
        a.text(xp + 0.01 * max_sys, 6, lab, ha="left", va="center", fontsize=6.3)
    _style_overnight(a, "Run Time (hrs)", "Total Event Rate")

    a = ax["B"]
    d = ch_d[within(ch_d["ChannelID"], 0, 260)]
    v = is_viable(d["ViableChannel"])
    a.scatter(d["Time"][~v], d["ChannelID"][~v], color="red", **PT)
    a.scatter(d["Time"][v], d["ChannelID"][v], color="green", **PT)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 0, 260, seq(0, 260, 50))
    _style_overnight(a, "Run Time (hrs)", "Channel Viability")

    a = ax["Base"]
    base_mean = chv.groupby("Time", as_index=False)["Baseline"].mean()
    d = chv[within(chv["Baseline"], 500, 2500)]
    a.scatter(d["Time"], d["Baseline"], color="deepskyblue", **PT)
    bm = base_mean[within(base_mean["Baseline"], 500, 2500)]
    a.scatter(bm["Time"], bm["Baseline"], color="black", **PT)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 500, 2500, seq(500, 2500, 500))
    _style_overnight(a, "Run Time (hrs)", "Baseline (mV)")

    a = ax["RMS"]
    d = chv[chv["SignalRMS"] < 0.08].copy()  # should check why this threshold value
    d["Mean"] = d.groupby("Time")["SignalRMS"].transform("mean")
    a.scatter(jitter(d["Time"], rng), jitter(d["SignalRMS"], rng), color="#79CDCD", **PT)  # darkslategray3
    mm = d.drop_duplicates("Time")
    a.scatter(mm["Time"], mm["Mean"], color="black", **PT)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 0, 0.08)
    _style_overnight(a, "Run Time (hrs)", "Signal RMS")

    a = ax["LVL1"]
    d = chv[chv["LevelOne"] != LEVEL_ONE_SENTINEL].copy()
    d["Mean"] = d.groupby("Time")["LevelOne"].transform("mean")
    jx, jy = jitter(d["Time"], rng), jitter(d["LevelOne"], rng)
    m = (jy >= 300) & (jy <= 1500)
    a.scatter(jx[m], jy[m], color="orange", **PT)
    mm = d.drop_duplicates("Time")
    mm = mm[within(mm["Mean"], 300, 1500)]
    a.scatter(mm["Time"], mm["Mean"], color="black", s=3, linewidths=0, rasterized=True)
    set_scale(a, "x", 0, max_ch, seq(0, max_ch, 1))
    set_scale(a, "y", 300, 1500)
    _style_overnight(a, "Run Time (hrs)", "Level 1 (uV)")

    for a in ax.values():
        _set_minor_midpoints(a)

    lvl1_clean = ch_d["LevelOne"].where(viable & (ch_d["LevelOne"] != LEVEL_ONE_SENTINEL))
    ch_avgs = {
        "Channel Activity (%)": round(100 * viable.sum() / len(ch_d)),
        "Baseline (mV)": round(np.nanmean(ch_d["Baseline"].where(viable))),
        "Level 1 (uV)": round(np.nanmean(lvl1_clean)),
        "Signal RMS": round(np.nanmean(ch_d["SignalRMS"].where(viable)), 4),
    }

    # ---- run metadata from RunData + protocol settings ----
    rd = run_data.loc[run_data["SampleID"] == run_id,
                      ["SampleID", "ProtocolName", "ReagentLot", "SettingsGroup"]]
    if protocol_settings is not None:
        rd = rd.merge(protocol_settings, on=["ProtocolName", "SettingsGroup"], how="left")
    setting_cols = [c for c in ["Target Baseline (mV)", "Target Bias (V)", "Applied Pressure (psi)"]
                    if c in rd.columns and rd[c].notna().any()]  # pivot_longer/drop_na/pivot_wider
    rd = rd.rename(columns={"SampleID": "Sample ID", "ProtocolName": "Protocol",
                            "SettingsGroup": "Settings", "ReagentLot": "Reagent Lot"})
    sample_cols = ["Sample ID", "Protocol", "Settings"] + setting_cols + ["Reagent Lot"]
    rd = rd[sample_cols].reset_index(drop=True)
    if rd.empty:
        rd = pd.DataFrame([{c: (run_id if c == "Sample ID" else None) for c in sample_cols}])

    avg_cols = ["Total Event Rate", "Channel Activity (%)", "Active Channel Count", "Baseline (mV)",
                "Level 1 (uV)", "Signal RMS", "Current (uA)", "Bias Voltage (V)"]
    avgs = {**ch_avgs, **sys_avgs}
    table = rd.copy()
    for c in avg_cols:
        table[c] = avgs[c]
    _draw_run_table(ax_tbl, table, sample_cols[1:], avg_cols)
    return fig


def overnight_run_plots(experiment_dir=None, out_dir=None, use_protocol_sheet=True):
    experiment_dir = experiment_dir or choose_experiment_dir()
    protocol_settings = build_protocol_settings_df() if use_protocol_sheet else None
    stamp = datetime.now().strftime("_%Y%m%d_%H%M%S")
    base = output_prefix(experiment_dir, out_dir)

    # sample ids present: between Data_/Metrics_ and .csv; tolerates sample-id typos
    run_ids = []
    for f in os.listdir(experiment_dir):
        rid = _first(r"(?:Data|Metrics)_(.+)(?=\.csv)", f)
        if rid is not None and rid not in run_ids:
            run_ids.append(rid)

    system_metrics, channel_data, run_data = read_experiment(experiment_dir)
    # one row per minute of run time (a snapshot, not a rolling average)
    channel_data = channel_data[channel_data["Time_sec"] % 60 == 0]

    saved = []
    for run_id in run_ids:
        sys_d = system_metrics[system_metrics["RunID"] == run_id]
        ch_d = channel_data[channel_data["RunID"] == run_id]
        if sys_d.empty or ch_d.empty:
            print(f"Skipping {run_id}: missing SystemMetrics or ChannelData")
            continue
        fig = _overnight_run_figure(run_id, sys_d, ch_d, run_data, protocol_settings)
        path = os.path.join(base, f"{run_id}_overnight_instrument_metrics{stamp}.jpg")
        fig.savefig(path, dpi=JPG_DPI)
        plt.close(fig)
        print("Saved", path)
        saved.append(path)
    return saved


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
        for g, gd in d.groupby(group, sort=True):
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


def overlay_run_plots(experiment_dir=None, out_dir=None):
    experiment_dir = experiment_dir or choose_experiment_dir()
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
    cdv = cd[is_viable(cd["ViableChannel"])]
    base_df = cdv.copy()
    base_df["Mean"] = base_df.groupby(["Time_sec", "RunIDRecord"])["Baseline"].transform("mean")
    rms_df = cdv[cdv["SignalRMS"] < 0.1].copy()
    rms_df["Mean"] = rms_df.groupby(["Time_sec", "RunIDRecord"])["SignalRMS"].transform("mean")
    rms_df = rms_df[within(rms_df["Mean"], 0, 0.07)]
    lvl_df = cdv[cdv["LevelOne"] != LEVEL_ONE_SENTINEL].copy()
    # NB: the R code groups LVL1 by `Time` only (not Time_sec + RunIDRecord like the others),
    # so runs whose timestamps line up get averaged together. Kept as-is to match.
    lvl_df["Mean"] = lvl_df.groupby("Time")["LevelOne"].transform("mean")

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
    cdb = cd[within(cd["ChannelID"], 0, 260)]
    viable = is_viable(cdb["ViableChannel"])
    for i, inj in enumerate(inj_rows):
        for j, wd in enumerate(cd_facets):
            a = axes[i, j]
            m = (cdb["Injection"] == inj) & (cdb["WaferDie"] == wd)
            for flag, col in [(False, "red"), (True, "green")]:
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
                   for c, l in [("red", "FALSE"), ("green", "TRUE")]]
    band.legend(handles=inj_handles, title="Injection", loc="center", bbox_to_anchor=(0.4, 0.5),
               ncol=len(inj_handles), fontsize=12, title_fontsize=12, frameon=False)
    band.legend(handles=via_handles, title="ViableChannel", loc="center", bbox_to_anchor=(0.8, 0.5),
               ncol=2, fontsize=12, title_fontsize=12, frameon=False)
    # format_delim(batch_wafer_dies, "", eol="_") also writes the column header, hence "WaferDie_"
    save_name = "WaferDie_" + "".join(f"{wd}_" for wd in unique_in_order(sm["WaferDie"]))
    path = os.path.join(base, f"{save_name}overlay_instrument_metrics{stamp}.jpg")
    fig.savefig(path, dpi=JPG_DPI)
    plt.close(fig)
    print("Saved", path)
    return path


# --------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["overnight", "overlay"])
    p.add_argument("--dir", help="experiment folder (default: pick a file in a dialog)")
    p.add_argument("--out", help="output folder (default: OUTPUT_BASE, else the experiment folder)")
    p.add_argument("--no-sheet", action="store_true",
                   help="overnight only: skip the Google Sheets protocol-settings lookup")
    args = p.parse_args()
    if args.mode == "overnight":
        overnight_run_plots(args.dir, args.out, use_protocol_sheet=not args.no_sheet)
    else:
        overlay_run_plots(args.dir, args.out)
