"""Generate benchmark charts for the README and benchmark-results doc.

Run: python docs/generate_charts.py
Output: docs/images/*.png
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

# ── Palette ──────────────────────────────────────────────────────────────────
INDIGO      = "#6366f1"
INDIGO_PALE = "#a5b4fc"
INDIGO_DARK = "#4338ca"
SLATE_50    = "#f8fafc"
SLATE_200   = "#e2e8f0"
SLATE_400   = "#94a3b8"
SLATE_600   = "#475569"
SLATE_800   = "#1e293b"
GREEN       = "#22c55e"
AMBER       = "#f59e0b"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.spines.left":  False,
    "axes.grid":         True,
    "axes.grid.axis":    "x",
    "grid.color":        SLATE_200,
    "grid.linewidth":    0.8,
    "text.color":        SLATE_800,
    "axes.labelcolor":   SLATE_600,
    "xtick.color":       SLATE_600,
    "ytick.color":       SLATE_800,
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
})

OUT = Path(__file__).parent / "images"
OUT.mkdir(exist_ok=True)


# ── 1. Token Reduction by Corpus ─────────────────────────────────────────────
def chart_token_reduction_by_corpus():
    labels   = ["Fixture\n(tiny, 2 files)", "psf/requests\n(~15k LOC)", "pallets/flask\n(~30k LOC)", "encode/httpx\n(~20k LOC)"]
    values   = [24, 89, 92, 93]
    colors   = [INDIGO_PALE, INDIGO, INDIGO, INDIGO_DARK]

    fig, ax = plt.subplots(figsize=(8, 3.6))
    bars = ax.barh(labels, values, color=colors, height=0.52, zorder=3)

    # Value labels
    for bar, v in zip(bars, values):
        ax.text(
            bar.get_width() + 1.2, bar.get_y() + bar.get_height() / 2,
            f"{v}%", va="center", ha="left", fontsize=12,
            fontweight="bold", color=SLATE_800,
        )

    # 60 % target line (the stated minimum claim)
    ax.axvline(60, color=SLATE_400, linewidth=1, linestyle="--", zorder=2)
    ax.text(60.8, -0.62, "60% target", fontsize=9, color=SLATE_400, va="bottom")

    ax.set_xlim(0, 105)
    ax.set_xlabel("Token reduction vs raw file reading (%)", labelpad=8)
    ax.set_title("Token Reduction by Corpus", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    fig.tight_layout()
    fig.savefig(OUT / "token_reduction_by_corpus.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK token_reduction_by_corpus.png")


# ── 2. Accuracy: CodePrism vs Baseline ───────────────────────────────────────
def chart_accuracy_comparison():
    corpora  = ["psf/requests", "pallets/flask", "encode/httpx"]
    cp_vals  = [0.87, 0.64, 0.70]
    bl_vals  = [0.86, 0.77, 0.68]

    y     = np.arange(len(corpora))
    h     = 0.32
    gap   = 0.04

    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.barh(y + h / 2 + gap / 2, cp_vals, h, color=INDIGO,      label="CodePrism", zorder=3)
    ax.barh(y - h / 2 - gap / 2, bl_vals, h, color=INDIGO_PALE, label="Baseline (raw files)", zorder=3)

    for i, (cp, bl) in enumerate(zip(cp_vals, bl_vals)):
        ax.text(cp + 0.01, i + h / 2 + gap / 2, f"{cp:.2f}", va="center", ha="left", fontsize=10, fontweight="bold", color=SLATE_800)
        ax.text(bl + 0.01, i - h / 2 - gap / 2, f"{bl:.2f}", va="center", ha="left", fontsize=10, color=SLATE_600)

    ax.set_xlim(0, 1.08)
    ax.set_xlabel("LLM-as-judge accuracy score (0–1)", labelpad=8)
    ax.set_yticks(y)
    ax.set_yticklabels(corpora)
    ax.set_title("Answer Accuracy — CodePrism vs Raw File Baseline", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    ax.legend(frameon=False, fontsize=10, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "accuracy_comparison.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK accuracy_comparison.png")


# ── 3. Token Reduction by Query Type ─────────────────────────────────────────
def chart_token_reduction_by_query_type():
    types  = ["symbol_lookup", "call_trace", "impact_analysis", "dependency_map"]
    values = [87, 90, 89, 95]

    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    bars = ax.bar(types, values, color=INDIGO, width=0.52, zorder=3)

    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.6,
            f"{v}%", ha="center", va="bottom", fontsize=12, fontweight="bold", color=SLATE_800,
        )

    ax.set_ylim(0, 105)
    ax.set_ylabel("Avg token reduction (%)", labelpad=8)
    ax.set_title("Token Reduction by Query Type\n(avg across 3 production corpora)", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.tick_params(axis="x", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "token_reduction_by_query_type.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK token_reduction_by_query_type.png")


# ── 4. Accuracy Improvement Over Time (requests corpus) ──────────────────────
def chart_accuracy_over_time():
    milestones = ["v0.1.5\n(initial run)", "v0.1.6\n(dep latency fix)", "v0.1.7\n(GT calibration)"]
    cp_vals    = [0.66, 0.66, 0.87]
    bl_vals    = [0.81, 0.81, 0.86]

    x = np.arange(len(milestones))
    w = 0.32

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(x - w / 2, cp_vals, w, color=INDIGO,      label="CodePrism", zorder=3)
    ax.bar(x + w / 2, bl_vals, w, color=INDIGO_PALE, label="Baseline",  zorder=3)

    for i, (cp, bl) in enumerate(zip(cp_vals, bl_vals)):
        ax.text(i - w / 2, cp + 0.01, f"{cp:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold", color=SLATE_800)
        ax.text(i + w / 2, bl + 0.01, f"{bl:.2f}", ha="center", va="bottom", fontsize=10, color=SLATE_600)

    # Improvement arrow on last bar pair
    ax.annotate(
        "+32%", xy=(2 - w / 2, 0.87), xytext=(2 - w / 2, 0.72),
        ha="center", fontsize=10, color=GREEN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5),
    )

    ax.set_ylim(0, 1.05)
    ax.set_xticks(x)
    ax.set_xticklabels(milestones)
    ax.set_ylabel("LLM-as-judge accuracy score (0–1)", labelpad=8)
    ax.set_title("Accuracy Improvement Over Time — psf/requests", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.tick_params(axis="x", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "accuracy_over_time.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK accuracy_over_time.png")


# ── 5. Query Latency (p50 + p95) ─────────────────────────────────────────────
def chart_query_latency():
    tools  = ["get_context", "get_callers", "get_impact", "get_dependencies"]
    p50    = [1.2, 1.2, 2.0, 3.8]
    p95    = [1.8, 1.8, 3.4, 5.1]

    y   = np.arange(len(tools))
    h   = 0.32
    gap = 0.04

    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.barh(y + h / 2 + gap / 2, p50, h, color=INDIGO,      label="p50", zorder=3)
    ax.barh(y - h / 2 - gap / 2, p95, h, color=INDIGO_PALE, label="p95", zorder=3)

    for i, (a, b) in enumerate(zip(p50, p95)):
        ax.text(a + 0.08, i + h / 2 + gap / 2, f"{a} ms", va="center", ha="left", fontsize=10, fontweight="bold", color=SLATE_800)
        ax.text(b + 0.08, i - h / 2 - gap / 2, f"{b} ms", va="center", ha="left", fontsize=10, color=SLATE_600)

    ax.set_xlim(0, 7.5)
    ax.set_xlabel("Latency on psf/requests (ms, engine held open)", labelpad=8)
    ax.set_yticks(y)
    ax.set_yticklabels(tools)
    ax.set_title("Query Latency — p50 and p95", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    ax.legend(frameon=False, fontsize=10)

    # LLM inference reference
    ax.axvline(500, color=SLATE_400, linewidth=0.8, linestyle=":", zorder=2)  # would be off chart
    note = "LLM inference: 500–3000ms\n(CodePrism overhead < 0.5% of turn time)"
    ax.text(6.8, 3.6, note, fontsize=8, color=SLATE_400, ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=SLATE_50, edgecolor=SLATE_200))

    fig.tight_layout()
    fig.savefig(OUT / "query_latency.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK query_latency.png")


# ── 6. get_dependencies Latency Fix ──────────────────────────────────────────
def chart_deps_latency_fix():
    labels = ["v0.1.5\nSELECT * (full scan)", "v0.1.6\nSELECT DISTINCT (indexed)"]
    values = [10.7, 3.8]
    colors = [INDIGO_PALE, INDIGO]

    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    bars = ax.bar(labels, values, color=colors, width=0.42, zorder=3)

    for bar, v in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15,
            f"{v} ms", ha="center", va="bottom", fontsize=12, fontweight="bold", color=SLATE_800,
        )

    # Improvement annotation
    ax.annotate(
        "−64%", xy=(1, 3.8), xytext=(0.5, 8.0),
        ha="center", fontsize=12, color=GREEN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5),
    )

    ax.set_ylim(0, 13)
    ax.set_ylabel("p50 latency (ms)", labelpad=8)
    ax.set_title("get_dependencies Latency Fix (v0.1.6)", fontweight="bold", fontsize=13, pad=14, loc="left")
    ax.tick_params(axis="x", length=0, pad=8)
    ax.spines["bottom"].set_color(SLATE_200)
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "deps_latency_fix.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  OK deps_latency_fix.png")


if __name__ == "__main__":
    print("Generating benchmark charts...")
    chart_token_reduction_by_corpus()
    chart_accuracy_comparison()
    chart_token_reduction_by_query_type()
    chart_accuracy_over_time()
    chart_query_latency()
    chart_deps_latency_fix()
    print(f"\nAll charts written to {OUT.resolve()}")
