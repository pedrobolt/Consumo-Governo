"""
Geração de gráficos para o projeto Consumo do Governo Trimestral.

Gráficos produzidos:
  1. Série estimada vs. CNT publicada (Gráfico 1 do paper + extensão)
  2. Tabela de desvios percentuais por trimestre
  3. Comparativo de todos os métodos de desagregação
  4. Ranking de especificações por RMSE
  5. Decomposição do indicador por ente
  6. Gráfico de erros acumulados
  7. Heatmap de métricas por método
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path
from typing import Dict, Optional

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

COLORS = {
    "cnt":       "#1a5276",   # Azul escuro — série oficial
    "estimada":  "#e74c3c",   # Vermelho — série estimada
    "denton_prop": "#27ae60", # Verde — Denton proporcional
    "denton_add":  "#f39c12", # Laranja — Denton aditivo
    "chow_lin":    "#8e44ad", # Roxo — Chow-Lin
    "fernandez":   "#2980b9", # Azul — Fernandez
    "litterman":   "#16a085", # Verde-azul — Litterman
    "pro_rata":    "#95a5a6", # Cinza — baseline
}


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 1: Série Estimada vs. CNT (réplica do paper + extensão)
# ──────────────────────────────────────────────────────────────────────────────

def plot_series_comparison(cnt: pd.Series,
                            estimated: pd.Series,
                            title: str = "Consumo Nominal do Governo: CNT vs. Estimativa",
                            filename: str = "fig1_serie_comparacao.png") -> Path:
    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(cnt.index, cnt.values, label="CNT (série oficial)", color=COLORS["cnt"],
            linewidth=2, zorder=3)
    ax.plot(estimated.index, estimated.values, label="Série Estimada",
            color=COLORS["estimada"], linewidth=1.8, linestyle="--", zorder=2)

    # Banda de sombra entre as duas curvas
    ax.fill_between(cnt.index, cnt.values, estimated.values,
                    alpha=0.12, color="#e74c3c")

    # Linha vertical separando período do paper e extensão (se 2014 está no índice)
    if pd.Timestamp("2015-01-01") in cnt.index or any(i.year == 2015 for i in cnt.index):
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


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 2: Desvios percentuais
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 3: Comparativo de todos os métodos de desagregação
# ──────────────────────────────────────────────────────────────────────────────

def plot_methods_comparison(cnt: pd.Series,
                            methods_dict: Dict[str, pd.Series],
                            filename: str = "fig3_comparativo_metodos.png") -> Path:
    n_methods = len(methods_dict)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Painel esquerdo: séries em nível
    ax = axes[0]
    ax.plot(cnt.index, cnt.values, label="CNT", color=COLORS["cnt"],
            linewidth=2, zorder=10)
    method_colors = list(COLORS.values())[2:]
    for i, (name, series) in enumerate(methods_dict.items()):
        c = method_colors[i % len(method_colors)]
        ax.plot(series.index, series.values, label=name, color=c,
                linewidth=1.2, alpha=0.8, linestyle="--")
    ax.set_title("Nível (R$ bilhões)")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    # Painel direito: MAPE por método
    ax2 = axes[1]
    mapes = {}
    for name, series in methods_dict.items():
        aligned = series.reindex(cnt.index).dropna()
        cnt_aligned = cnt.reindex(aligned.index)
        e = 100 * np.mean(np.abs((aligned - cnt_aligned) / cnt_aligned))
        mapes[name] = e

    bars = ax2.barh(list(mapes.keys()), list(mapes.values()),
                    color=[method_colors[i % len(method_colors)]
                           for i in range(len(mapes))],
                    alpha=0.8)
    ax2.axvline(2, color="green", linestyle="--", linewidth=1,
                label="Target: MAPE < 2%")
    ax2.set_xlabel("MAPE (%)")
    ax2.set_title("MAPE por Método")
    ax2.legend(fontsize=8)
    ax2.grid(axis="x", alpha=0.3)

    plt.suptitle("Comparativo de Métodos de Desagregação Temporal", fontsize=12, y=1.01)
    plt.tight_layout()

    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 4: Ranking de especificações
# ──────────────────────────────────────────────────────────────────────────────

def plot_specification_ranking(ranking_df: pd.DataFrame,
                                metric: str = "RMSE",
                                filename: str = "fig4_ranking_specs.png") -> Path:
    df = ranking_df.sort_values(metric).head(15)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(range(len(df)), df[metric].values,
                   color=["#27ae60" if i == 0 else "#3498db" if i < 3
                          else "#95a5a6" for i in range(len(df))],
                   alpha=0.85)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["model"].values, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel(f"{metric} (R$ bilhões)")
    ax.set_title(f"Ranking das Especificações por {metric} (top 15)")
    ax.grid(axis="x", alpha=0.3)

    # Valores nas barras
    for i, (bar, val) in enumerate(zip(bars, df[metric].values)):
        ax.text(val + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.3f}", va="center", fontsize=8)

    plt.tight_layout()
    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 5: Heatmap de métricas
# ──────────────────────────────────────────────────────────────────────────────

def plot_metrics_heatmap(metrics_df: pd.DataFrame,
                          filename: str = "fig5_heatmap_metricas.png") -> Path:
    numeric_cols = ["RMSE", "MAE", "MAPE", "Corr", "TheilU1"]
    cols = [c for c in numeric_cols if c in metrics_df.columns]

    if not cols:
        return OUTPUT_CHARTS / filename

    df_plot = metrics_df.set_index("model")[cols].astype(float)

    # Normalizar para heatmap (0=melhor, 1=pior) por coluna
    df_norm = df_plot.copy()
    for col in cols:
        if col == "Corr":
            df_norm[col] = 1 - (df_plot[col] - df_plot[col].min()) / \
                (df_plot[col].max() - df_plot[col].min() + 1e-9)
        else:
            df_norm[col] = (df_plot[col] - df_plot[col].min()) / \
                (df_plot[col].max() - df_plot[col].min() + 1e-9)

    fig, ax = plt.subplots(figsize=(10, max(4, len(df_norm) * 0.4 + 2)))
    sns.heatmap(df_norm, annot=df_plot.round(3), fmt="g",
                cmap="RdYlGn_r", ax=ax, linewidths=0.5,
                cbar_kws={"shrink": 0.8, "label": "Normalizado (0=melhor)"})
    ax.set_title("Métricas de Validação por Modelo")
    ax.set_xlabel("")
    plt.tight_layout()

    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Gráfico 6: Dashboard completo (figura composta)
# ──────────────────────────────────────────────────────────────────────────────

def plot_dashboard(cnt: pd.Series,
                   best_estimated: pd.Series,
                   methods_dict: Dict[str, pd.Series],
                   metrics_df: pd.DataFrame,
                   filename: str = "fig6_dashboard.png") -> Path:
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, hspace=0.4, wspace=0.35)

    # ─ Painel 1: Nível ────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(cnt.index, cnt.values, label="CNT Publicada", color=COLORS["cnt"],
             linewidth=2.5)
    ax1.plot(best_estimated.index, best_estimated.values, label="Melhor Estimativa",
             color=COLORS["estimada"], linewidth=1.8, linestyle="--")
    if len(methods_dict) > 0:
        for name, s in list(methods_dict.items())[:4]:
            c = list(COLORS.values())[3 + list(methods_dict.keys()).index(name)]
            ax1.plot(s.index, s.values, alpha=0.4, linewidth=1, color=c, linestyle=":")
    ax1.set_title("Consumo Nominal do Governo – CNT vs. Estimativas (R$ bilhões)")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # ─ Painel 2: Desvios % ───────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    errors = 100 * (best_estimated.reindex(cnt.index) - cnt) / cnt
    colors_bars = ["#e74c3c" if e > 0 else "#2980b9" for e in errors.values]
    ax2.bar(range(len(errors)), errors.values, color=colors_bars, alpha=0.7)
    ax2.axhline(0, color="black", lw=0.8)
    ax2.axhline(3, color="orange", lw=0.8, ls="--", alpha=0.7)
    ax2.axhline(-3, color="orange", lw=0.8, ls="--", alpha=0.7)
    ax2.set_title("Desvio % (Estimada - CNT)")
    ax2.set_ylabel("Desvio (%)")
    ax2.grid(alpha=0.3)

    # ─ Painel 3: MAPE por ano ─────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    df_err = pd.DataFrame({"cnt": cnt, "est": best_estimated.reindex(cnt.index)}).dropna()
    if not df_err.empty:
        df_err["mape_q"] = 100 * np.abs(df_err["est"] - df_err["cnt"]) / df_err["cnt"]
        annual_mape = df_err.groupby(df_err.index.year)["mape_q"].mean()
        ax3.bar(annual_mape.index, annual_mape.values, color="#3498db", alpha=0.8)
        ax3.axhline(2, color="green", ls="--", lw=1, label="Target 2%")
        ax3.set_title("MAPE Médio Anual (%)")
        ax3.set_xlabel("Ano")
        ax3.legend(fontsize=8)
        ax3.grid(alpha=0.3)

    # ─ Painel 4: Ranking RMSE ──────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    if "RMSE" in metrics_df.columns and "model" in metrics_df.columns:
        top = metrics_df.sort_values("RMSE").head(8)
        colors_bar = ["#27ae60" if i == 0 else "#3498db" if i < 3
                      else "#95a5a6" for i in range(len(top))]
        ax4.barh(range(len(top)), top["RMSE"].values, color=colors_bar, alpha=0.85)
        ax4.set_yticks(range(len(top)))
        ax4.set_yticklabels(top["model"].values, fontsize=8)
        ax4.invert_yaxis()
        ax4.set_title("Ranking por RMSE (R$ bilhões)")
        ax4.grid(alpha=0.3)

    # ─ Painel 5: Correlação por método ─────────────────────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    if "Corr" in metrics_df.columns and "MAPE" in metrics_df.columns:
        scatter_colors = ["#e74c3c" if mape <= 2 else "#3498db"
                          for mape in metrics_df["MAPE"].values]
        ax5.scatter(metrics_df["MAPE"], metrics_df["Corr"],
                    c=scatter_colors, s=80, alpha=0.8, zorder=5)
        for _, row in metrics_df.iterrows():
            ax5.annotate(row["model"], (row["MAPE"], row["Corr"]),
                         fontsize=7, alpha=0.8,
                         xytext=(3, 3), textcoords="offset points")
        ax5.axvline(2, color="green", ls="--", lw=0.8)
        ax5.axhline(0.98, color="orange", ls="--", lw=0.8)
        ax5.set_xlabel("MAPE (%)")
        ax5.set_ylabel("Correlação")
        ax5.set_title("MAPE vs. Correlação por Modelo")
        ax5.grid(alpha=0.3)

    plt.suptitle(
        "Dashboard: Consumo do Governo Nominal Trimestral – Metodologia e Validação",
        fontsize=13, y=1.01, fontweight="bold")

    path = OUTPUT_CHARTS / filename
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
