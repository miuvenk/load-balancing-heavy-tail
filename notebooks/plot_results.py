"""
Plot the smoke-test / experiment results.

Reads every CSV in ``data/`` (the format written by src/dispatcher.py) and
produces four PNG figures in ``notebooks/figures/``:

    percentiles.png   Grouped bar chart of mean / p50 / p90 / p99 per policy
                      (log Y so the tail outliers don't dwarf the body)
    ccdf.png          Complementary CDF P(R > r) per policy on log-log axes.
                      This is the canonical plot for heavy-tailed response
                      times - linear slope on a log-log plot indicates the
                      tail index.
    per_request.png   Scatter: response time vs request_id, one subplot
                      per policy, colored by which server handled the
                      request. Useful for spotting clustered slow runs.
    load_split.png    Horizontal stacked bar showing how many of the
                      requests were sent to each server under each policy.

Usage:
    python notebooks/plot_results.py
    python notebooks/plot_results.py --data data --out notebooks/figures

The script picks up whichever policy CSVs happen to be in ``--data``. It
auto-derives the policy name from the file name (everything before the
first ``.``) so files like ``random.csv``, ``random_lam8.0_alpha1.3.csv``,
or ``sita_run2.csv`` all work.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np


# Ordering and colors are stable so the legend reads consistently across runs.
POLICY_ORDER = ["random", "round_robin", "jsq", "lwl", "sita"]
POLICY_COLOR = {
    "random":      "#888780",
    "round_robin": "#85B7EB",
    "jsq":         "#378ADD",
    "lwl":         "#D85A30",
    "sita":        "#1D9E75",
}
SERVER_COLOR = {
    5001: "#1D9E75",
    5002: "#7F77DD",
    5003: "#D85A30",
}
PCT_COLOR = {
    "mean": "#888780",
    "p50":  "#85B7EB",
    "p90":  "#378ADD",
    "p99":  "#0C447C",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> List[dict]:
    """Read one dispatcher CSV into a list of dict rows."""
    out: List[dict] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            row["x"] = float(row["x"])
            row["response_time"] = float(row["response_time"])
            row["service_time"] = float(row["service_time"])
            row["wait_time"] = float(row["wait_time"])
            row["server_port"] = int(row["server_port"])
            row["request_id"] = int(row["request_id"])
            out.append(row)
    return out


def load_all(data_dir: Path) -> Dict[str, List[dict]]:
    """Return {policy_name: rows} for every CSV in data_dir."""
    runs: Dict[str, List[dict]] = {}
    for f in sorted(data_dir.glob("*.csv")):
        # policy = first segment of the file name before any underscore or dot
        name = f.stem
        for sep in ("_lam", "_alpha", "_run"):
            if sep in name:
                name = name.split(sep)[0]
                break
        runs[name] = load_csv(f)
    return runs


def sort_policies(runs: Dict[str, List[dict]]) -> List[str]:
    known = [p for p in POLICY_ORDER if p in runs]
    extra = sorted(p for p in runs if p not in POLICY_ORDER)
    return known + extra


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def percentiles(rt: np.ndarray) -> dict:
    return {
        "mean": float(rt.mean()) * 1000.0,
        "p50":  float(np.percentile(rt, 50)) * 1000.0,
        "p90":  float(np.percentile(rt, 90)) * 1000.0,
        "p99":  float(np.percentile(rt, 99)) * 1000.0,
        "max":  float(rt.max()) * 1000.0,
    }


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_percentiles(runs, policies, out: Path):
    metrics = ["mean", "p50", "p90", "p99"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    n = len(policies)
    w = 0.2
    x = np.arange(n)

    for i, m in enumerate(metrics):
        ys = [percentiles(np.array([r["response_time"] for r in runs[p]]))[m]
              for p in policies]
        ax.bar(x + (i - 1.5) * w, ys, w, label=m, color=PCT_COLOR[m])

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(policies)
    ax.set_ylabel("response time (ms, log scale)")
    ax.set_title("Response-time percentiles by policy")
    ax.legend(loc="upper left", ncol=4, frameon=False, fontsize=9)
    ax.grid(True, which="both", axis="y", linestyle=":", alpha=0.35)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out / "percentiles.png", dpi=140)
    plt.close(fig)


def plot_ccdf(runs, policies, out: Path):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for p in policies:
        rt = np.sort(np.array([r["response_time"] for r in runs[p]])) * 1000.0
        n = len(rt)
        if n == 0:
            continue
        # CCDF: P(R > r). Empirical survival function.
        surv = 1.0 - np.arange(1, n + 1) / n
        # Drop the trailing zero so the log plot terminates cleanly.
        ax.step(rt[:-1], surv[:-1],
                where="post", label=p,
                color=POLICY_COLOR.get(p, "#444444"), linewidth=1.5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("response time (ms)")
    ax.set_ylabel("P(R > t)")
    ax.set_title("Response-time CCDF (heavy-tail view)")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.grid(True, which="both", linestyle=":", alpha=0.35)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out / "ccdf.png", dpi=140)
    plt.close(fig)


def plot_per_request(runs, policies, out: Path):
    cols = min(len(policies), 3)
    rows = (len(policies) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 2.8 * rows),
                             sharey=True, squeeze=False)
    for i, p in enumerate(policies):
        ax = axes[i // cols][i % cols]
        rows_p = runs[p]
        ids = np.array([r["request_id"] for r in rows_p])
        rt  = np.array([r["response_time"] for r in rows_p]) * 1000.0
        ports = np.array([r["server_port"] for r in rows_p])
        for port in sorted(set(ports)):
            mask = ports == port
            ax.scatter(ids[mask], rt[mask], s=24,
                       color=SERVER_COLOR.get(port, "#444"),
                       label=str(port), edgecolors="none", alpha=0.85)
        ax.set_yscale("log")
        ax.set_title(p, fontsize=10)
        ax.grid(True, which="both", linestyle=":", alpha=0.35)
        ax.set_axisbelow(True)
        if i % cols == 0:
            ax.set_ylabel("response (ms)")
        if i // cols == rows - 1:
            ax.set_xlabel("request id")
    # Hide unused axes
    for j in range(len(policies), rows * cols):
        axes[j // cols][j % cols].axis("off")
    # One legend for the whole figure
    handles = [plt.Line2D([], [], marker='o', linestyle='',
                          color=SERVER_COLOR[p], label=f"server {p}")
               for p in sorted(SERVER_COLOR)]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles),
               frameon=False, fontsize=9, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Per-request response times", y=1.02, fontsize=12)
    fig.tight_layout()
    fig.savefig(out / "per_request.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_load_split(runs, policies, out: Path):
    fig, ax = plt.subplots(figsize=(8, max(2.5, 0.6 * len(policies) + 1)))
    counts_by_port = defaultdict(list)
    for p in policies:
        ports = [r["server_port"] for r in runs[p]]
        for port in sorted(SERVER_COLOR):
            counts_by_port[port].append(ports.count(port))
    y = np.arange(len(policies))
    left = np.zeros(len(policies))
    for port, color in SERVER_COLOR.items():
        vals = np.array(counts_by_port[port])
        ax.barh(y, vals, left=left, color=color, label=f"server {port}",
                edgecolor="white", linewidth=0.5)
        left += vals
    ax.set_yticks(y)
    ax.set_yticklabels(policies)
    ax.invert_yaxis()
    ax.set_xlabel("number of requests")
    ax.set_title("Request count per server by policy")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.grid(True, axis="x", linestyle=":", alpha=0.35)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out / "load_split.png", dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Summary table to stdout
# ---------------------------------------------------------------------------

def print_summary_table(runs, policies):
    print()
    print(f"{'policy':<14}{'n':>5}{'mean':>10}{'p50':>10}"
          f"{'p90':>10}{'p99':>10}{'max':>12}")
    print("-" * 70)
    for p in policies:
        rt = np.array([r["response_time"] for r in runs[p]])
        s = percentiles(rt)
        print(f"{p:<14}{len(rt):>5}"
              f"{s['mean']:>9.1f}ms"
              f"{s['p50']:>9.1f}ms"
              f"{s['p90']:>9.1f}ms"
              f"{s['p99']:>9.1f}ms"
              f"{s['max']:>11.1f}ms")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=Path("data"),
                   help="directory containing dispatcher CSVs (default: data)")
    p.add_argument("--out", type=Path, default=Path("notebooks/figures"),
                   help="directory for PNG output (default: notebooks/figures)")
    args = p.parse_args()

    runs = load_all(args.data)
    if not runs:
        raise SystemExit(f"No CSV files found in {args.data}")
    policies = sort_policies(runs)

    args.out.mkdir(parents=True, exist_ok=True)

    print_summary_table(runs, policies)

    plot_percentiles(runs, policies, args.out)
    plot_ccdf(runs, policies, args.out)
    plot_per_request(runs, policies, args.out)
    plot_load_split(runs, policies, args.out)

    print(f"Wrote 4 figures to {args.out}/")
    for f in sorted(args.out.glob("*.png")):
        print(f"  - {f}")


if __name__ == "__main__":
    main()
