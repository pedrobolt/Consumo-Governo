"""
Generate all output files:
  output/tables/ranking_final.csv
  output/tables/diagnostico_gap.csv
  output/tables/desvios_trimestre.csv
  output/figures/cnt_vs_best_estimate.png
  output/figures/desvios_percentuais.png
"""

import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FREQ, OUTPUT_TABLES, OUTPUT_CHARTS
from src.disaggregation.denton import (
    denton_proportional, denton_additive, denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import chow_lin, fernandez, litterman
from src.validation.metrics import compute_all_metrics

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
OUTPUT_CHARTS.mkdir(parents=True, exist_ok=True)

# ── Load data ─────────────────────────────────────────────────────────────────

cnt = pd.read_csv(ROOT / "data/raw/cnt_quarterly.csv")
cnt["data"] = pd.to_datetime(cnt["periodo"].str.replace(
    r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
cnt = cnt.sort_values("data").set_index("data")["cnt_nominal_bi"]
cnt_annual = cnt.groupby(cnt.index.year).sum()

fiscal = pd.read_csv(ROOT / "data/raw/siconfi_fiscal.csv")
fiscal["data"] = pd.to_datetime(fiscal["periodo"].str.replace(
    r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))

METHODS = {
    "denton_prop":    denton_proportional,
    "denton_add":     denton_additive,
    "denton_prop_d2": denton_second_diff_proportional,
    "pro_rata":       pro_rata,
    "chow_lin":       chow_lin,
    "fernandez":      fernandez,
    "litterman":      litterman,
}

# ── Disaggregate all specs x methods ─────────────────────────────────────────

def disaggregate_spec(spec_name):
    spec = (fiscal[fiscal["spec"] == spec_name]
            .set_index("data")["valor_bi"].sort_index())
    common = sorted(set(spec.index.year.unique()) & set(cnt_annual.index.tolist()))
    if len(common) < 2:
        return {}
    ind = spec[spec.index.year.isin(common)]
    if len(ind) != len(common) * FREQ:
        return {}
    a_vec = cnt_annual.loc[common].values
    results = {}
    for mname, mfn in METHODS.items():
        try:
            q = mfn(ind.values, a_vec, FREQ)
            results[mname] = pd.Series(q, index=ind.index)
        except Exception:
            pass
    return results

all_estimates = {}
for spec_name in fiscal["spec"].unique():
    for mname, series in disaggregate_spec(spec_name).items():
        all_estimates[f"{spec_name}_{mname}"] = series

# ── Per-model metrics ─────────────────────────────────────────────────────────

rows = []
for name, series in all_estimates.items():
    aligned_est = series.reindex(cnt.index).dropna()
    if len(aligned_est) < 8:
        continue
    aligned_actual = cnt.reindex(aligned_est.index)
    row = compute_all_metrics(aligned_actual.values, aligned_est.values, name=name)
    rows.append(row)

ranking = (pd.DataFrame(rows)
           .sort_values("MAPE")
           .reset_index(drop=True))
ranking.index = ranking.index + 1
ranking.index.name = "rank"
ranking.to_csv(OUTPUT_TABLES / "ranking_final.csv", float_format="%.4f")
print("Saved ranking_final.csv")
print(ranking[["model", "n", "RMSE", "MAPE", "Corr"]].head(10).to_string())

# ── Best model ────────────────────────────────────────────────────────────────

best_name = ranking.iloc[0]["model"]
best_series = all_estimates[best_name]

# ── Split-sample diagnostics ──────────────────────────────────────────────────

def split_metrics(est_series, label):
    aligned_est = est_series.reindex(cnt.index).dropna()
    aligned_actual = cnt.reindex(aligned_est.index)
    gap = aligned_est.index[aligned_est.index.year < 2018]
    post = aligned_est.index[aligned_est.index.year >= 2018]
    diag_rows = []
    for window, idx in [("2015Q1-2017Q4", gap), ("2018Q1-2024Q4", post),
                        ("2015Q1-2024Q4", aligned_est.index)]:
        if len(idx) < 4:
            continue
        ae = aligned_actual.loc[idx].values
        fe = aligned_est.loc[idx].values
        errs = ae - fe
        diag_rows.append(dict(
            model=label, window=window, n=len(idx),
            RMSE=float(np.sqrt((errs**2).mean())),
            MAPE=float((np.abs(errs) / ae * 100).mean()),
            Corr=float(np.corrcoef(ae, fe)[0, 1]),
        ))
    return diag_rows

diag_rows = []
for label in [best_name,
              "spec01_uniao_sal_ce_litterman",
              "spec13_uniao_estados_sal_ce_ci_chow_lin"]:
    if label in all_estimates:
        diag_rows.extend(split_metrics(all_estimates[label], label))

diag_df = pd.DataFrame(diag_rows)
diag_df.to_csv(OUTPUT_TABLES / "diagnostico_gap.csv", index=False, float_format="%.4f")
print("\nSaved diagnostico_gap.csv")
print(diag_df.to_string(index=False))

# ── Desvios por trimestre ─────────────────────────────────────────────────────

best_aligned = best_series.reindex(cnt.index).dropna()
actual_aligned = cnt.reindex(best_aligned.index)
dev_df = pd.DataFrame({
    "periodo": (best_aligned.index.year.astype(str)
                + "Q" + best_aligned.index.quarter.astype(str)),
    "cnt_bi": actual_aligned.values.round(4),
    "estimado_bi": best_aligned.values.round(4),
    "desvio_bi": (best_aligned.values - actual_aligned.values).round(4),
    "desvio_pct": ((best_aligned.values - actual_aligned.values)
                   / actual_aligned.values * 100).round(4),
})
dev_df["modelo"] = best_name
dev_df.to_csv(OUTPUT_TABLES / "desvios_trimestre.csv", index=False, float_format="%.4f")
print(f"\nSaved desvios_trimestre.csv ({len(dev_df)} rows)")

# ── Figure 1: CNT vs best estimate ────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(actual_aligned.index, actual_aligned.values,
        color="#1a5276", linewidth=2.0, label="CNT Publicada (IBGE)", zorder=3)
ax.plot(best_aligned.index, best_aligned.values,
        color="#e74c3c", linewidth=1.6, linestyle="--",
        label=f"Melhor estimativa ({best_name})", zorder=2)
ax.set_title("Consumo Final das Administracoes Publicas: CNT vs. Estimativa",
             fontsize=13, fontweight="bold")
ax.set_ylabel("R$ bilhoes (precos correntes)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.legend()
ax.grid(axis="y", linestyle=":", alpha=0.5)
fig.tight_layout()
fig.savefig(OUTPUT_CHARTS / "cnt_vs_best_estimate.png", dpi=150)
plt.close(fig)
print("Saved cnt_vs_best_estimate.png")

# ── Figure 2: % desvios por trimestre ────────────────────────────────────────

fig, ax = plt.subplots(figsize=(12, 4))
colors = ["#e74c3c" if v > 0 else "#2980b9" for v in dev_df["desvio_pct"]]
ax.bar(range(len(dev_df)), dev_df["desvio_pct"], color=colors, width=0.7)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_title("Desvio Percentual Trimestral: Estimativa - CNT (%)", fontsize=13, fontweight="bold")
ax.set_ylabel("Desvio (%)")
step = max(1, len(dev_df) // 10)
ax.set_xticks(range(0, len(dev_df), step))
ax.set_xticklabels(dev_df["periodo"].iloc[::step], rotation=45, ha="right", fontsize=8)
ax.grid(axis="y", linestyle=":", alpha=0.5)
fig.tight_layout()
fig.savefig(OUTPUT_CHARTS / "desvios_percentuais.png", dpi=150)
plt.close(fig)
print("Saved desvios_percentuais.png")

print(f"\nBest model: {best_name}")
print(f"RMSE={ranking.iloc[0]['RMSE']:.4f}  MAPE={ranking.iloc[0]['MAPE']:.2f}%  "
      f"Corr={ranking.iloc[0]['Corr']:.4f}")
