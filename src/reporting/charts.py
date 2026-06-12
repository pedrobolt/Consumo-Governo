"""Gráficos do projeto Consumo do Governo Trimestral."""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

from config import OUTPUT_CHARTS

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "figure.dpi": 150,
})

_CNT_COLOR = "#1a5276"
_EST_COLOR = "#e74c3c"


def plot_series_comparison(cnt: pd.Series,
                           estimated: pd.Series,
                           title: str = "Consumo Nominal do Governo: CNT vs. Estimativa",
                           filename: str = "fig1_serie_comparacao.png") -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(cnt.index, cnt.values, label="CNT (série oficial)",
            color=_CNT_COLOR, linewidth=2, zorder=3)
    ax.plot(estimated.index, estimated.values, label="Série Estimada",
            color=_EST_COLOR, linewidth=1.8, linestyle="--", zorder=2)
    ax.fill_between(cnt.index, cnt.values, estimated.values,
                    alpha=0.12, color=_EST_COLOR)

    if any(i.year == 2015 for i in cnt.index):
        ax.axvline(pd.Timestamp("2015-01-01"), color="#7f8c8d",
                   linestyle=":", linewidth=1.2, label="Início extensão (2015)")

    ax.set_title(title)
    ax.set_xlabel("Período")
    ax.set_ylabel("R$ bilhões (correntes)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax.legend(framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_pct_errors(cnt: pd.Series,
                    estimated: pd.Series,
                    filename: str = "fig2_desvios_pct.png") -> Path:
    errors_pct = 100 * (estimated - cnt) / cnt

    fig, ax = plt.subplots(figsize=(12, 4))
    colors = ["#e74c3c" if e > 0 else "#2980b9" for e in errors_pct.values]
    ax.bar(range(len(errors_pct)), errors_pct.values, color=colors, alpha=0.8)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline(3, color="orange", linewidth=0.8, linestyle="--", alpha=0.7,
               label="±3% (limite do paper)")
    ax.axhline(-3, color="orange", linewidth=0.8, linestyle="--", alpha=0.7)

    labels = [f"{i.year}/T{i.quarter}" for i in errors_pct.index]
    step = max(1, len(labels) // 20)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), step)],
                       rotation=45, ha="right", fontsize=8)

    ax.set_title("Desvio Percentual: Série Estimada vs. CNT")
    ax.set_ylabel("Desvio (%)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
