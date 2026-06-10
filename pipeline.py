"""
Pipeline principal: Consumo do Governo Nominal Trimestral.

ESTADO ATUAL: Infraestrutura pronta; aguardando dados reais.

Fases (quando dados reais estiverem disponíveis):
  1. Coleta de dados (IBGE CNT + SICONFI/SIGA Brasil)
  2. Construção das séries indicadoras (13 especificações do paper)
  3. Desagregação temporal (Denton proporcional/aditivo, Chow-Lin, Fernandez, Litterman)
  4. Validação (RMSE, MAE, MAPE, correlação, Theil U) contra CNT publicada
  5. Relatórios e gráficos

REQUISITO: dados reais devem estar em data/raw/ antes de executar.
Ver DATA_ACQUISITION.md para instruções de download.
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import (YEAR_START, YEAR_END, FREQ, OUTPUT_TABLES, OUTPUT_SERIES)
from src.disaggregation.denton import (
    denton_proportional, denton_additive, denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import chow_lin, fernandez, litterman, fit_and_extrapolate
from src.validation.metrics import compute_all_metrics, compare_models, deviation_table
from src.reporting.charts import (
    plot_series_comparison, plot_pct_errors, plot_methods_comparison,
    plot_specification_ranking, plot_metrics_heatmap, plot_dashboard
)
from src.reporting.reports import print_deviation_table, export_final_series

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_cnt_real(path: str = "data/raw/cnt_quarterly.csv") -> Tuple[pd.Series, pd.Series]:
    """
    Carrega série CNT trimestral e anual de arquivo CSV real.

    Formato esperado do CSV:
      periodo,cnt_nominal_bi
      2010Q1,163.11
      ...

    Returns
    -------
    cnt_quarterly : pd.Series indexed by pd.Timestamp (início do trimestre)
    cnt_annual    : pd.Series indexed by int year
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Arquivo de dados reais não encontrado: {p}\n"
            "Execute o download conforme DATA_ACQUISITION.md antes de rodar o pipeline."
        )

    df = pd.read_csv(p)
    df["data"] = pd.to_datetime(df["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
    df["ano"] = df["data"].dt.year
    df = df.sort_values("data").set_index("data")

    cnt_quarterly = df["cnt_nominal_bi"]
    # Only include years with all 4 quarters as annual benchmarks
    qcount = df.groupby("ano")["cnt_nominal_bi"].count()
    complete_years = qcount[qcount == FREQ].index
    cnt_annual = df.groupby("ano")["cnt_nominal_bi"].sum().loc[complete_years]
    return cnt_quarterly, cnt_annual


def load_fiscal_indicators(path: str = "data/raw/siconfi_fiscal.csv") -> Dict[str, pd.Series]:
    """
    Carrega indicadores fiscais do SICONFI/SIGA Brasil de arquivo CSV real.

    Formato esperado do CSV:
      periodo,spec,valor_bi
      2010Q1,serie13,65.42
      ...

    Returns
    -------
    dict {spec_name: pd.Series indexed by pd.Timestamp}
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Arquivo de indicadores fiscais não encontrado: {p}\n"
            "Execute o download conforme DATA_ACQUISITION.md antes de rodar o pipeline."
        )

    df = pd.read_csv(p)
    df["data"] = pd.to_datetime(df["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
    df = df.sort_values("data")

    result = {}
    for spec, grp in df.groupby("spec"):
        s = grp.set_index("data")["valor_bi"]
        s.name = spec
        result[spec] = s

    return result


def disaggregate_all(indicator_dict: Dict[str, pd.Series],
                     cnt_annual: pd.Series) -> Dict[str, pd.Series]:
    """
    Aplica todos os métodos de desagregação a todas as séries indicadoras.
    """
    denton_methods = {
        "denton_prop":    denton_proportional,
        "denton_add":     denton_additive,
        "denton_prop_d2": denton_second_diff_proportional,
    }
    regression_methods = {
        "chow_lin":  chow_lin,
        "fernandez": fernandez,
        "litterman": litterman,
    }

    estimates = {}

    for spec_name, indicator in indicator_dict.items():
        years_ind = sorted(indicator.index.year.unique())
        common = sorted(set(years_ind) & set(cnt_annual.index.tolist()))
        if len(common) < 2:
            logger.warning("Spec %s: menos de 2 anos em comum com CNT — ignorado.", spec_name)
            continue

        ind_a = indicator[indicator.index.year.isin(common)]
        if len(ind_a) != len(common) * FREQ:
            logger.warning("Spec %s: %d obs ≠ %d anos × 4 — ignorado.",
                           spec_name, len(ind_a), len(common))
            continue

        a_vec = cnt_annual.loc[common].values

        for mname, mfn in denton_methods.items():
            key = f"{spec_name}_{mname}"
            try:
                q = mfn(ind_a.values, a_vec, FREQ)
                estimates[key] = pd.Series(q, index=ind_a.index)
            except Exception as exc:
                logger.debug("Erro %s: %s", key, exc)

        key = f"{spec_name}_pro_rata"
        try:
            q = pro_rata(ind_a.values, a_vec, FREQ)
            estimates[key] = pd.Series(q, index=ind_a.index)
        except Exception as exc:
            logger.debug("Erro %s: %s", key, exc)

        for mname, mfn in regression_methods.items():
            key = f"{spec_name}_{mname}"
            try:
                q = mfn(ind_a.values, a_vec, FREQ)
                estimates[key] = pd.Series(q, index=ind_a.index)
            except Exception as exc:
                logger.debug("Erro %s: %s", key, exc)

    logger.info("%d estimativas geradas.", len(estimates))
    return estimates


def validate_all(estimates: Dict[str, pd.Series],
                 cnt_quarterly: pd.Series) -> pd.DataFrame:
    """Calcula métricas para todos os modelos contra CNT publicada real."""
    aligned_series: Dict[str, pd.Series] = {}
    for name, series in estimates.items():
        aligned = series.reindex(cnt_quarterly.index).dropna()
        if len(aligned) < 8:
            continue
        aligned_series[name] = aligned

    if not aligned_series:
        return pd.DataFrame()

    # Use the index of the first series as the common evaluation window
    eval_index = next(iter(aligned_series.values())).index
    actual = cnt_quarterly.reindex(eval_index).values
    forecasts_dict = {name: s.reindex(eval_index).values for name, s in aligned_series.items()}

    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    metrics_df = compare_models(actual, forecasts_dict)
    metrics_df.to_csv(OUTPUT_TABLES / "metricas_completas.csv", float_format="%.4f")
    return metrics_df


def select_best_denton_spec(metrics_df: pd.DataFrame):
    """Return (spec_name, mape, rmse) for the Denton-proportional model with lowest MAPE."""
    denton = metrics_df[metrics_df["model"].str.endswith("_denton_prop")].copy()
    if denton.empty:
        raise RuntimeError("No denton_prop models in metrics_df")
    best = denton.sort_values("MAPE").iloc[0]
    spec = best["model"].replace("_denton_prop", "")
    return spec, float(best["MAPE"]), float(best["RMSE"])


def _scale_partial_q2(spec_name: str, partial_value: float,
                      rreo_uniao_csv: str = "data/raw/siconfi_rreo_uniao.csv",
                      rreo_estados_csv: str = "data/raw/siconfi_rreo_estados.csv",
                      train_years: range = range(2015, 2026)) -> float:
    """
    Scale a partial 2026Q2 indicator (Bim2*0.5 only) to a full-quarter estimate.

    Historical ratio = mean(Bim2*0.5 / (Bim2*0.5 + Bim3)) over training years.
    Covers both estados-only and combined specs.
    """
    frames = []
    if "uniao" in spec_name or "spec03" in spec_name or "spec13" in spec_name:
        if Path(rreo_uniao_csv).exists():
            frames.append(pd.read_csv(rreo_uniao_csv))
    if Path(rreo_estados_csv).exists():
        frames.append(pd.read_csv(rreo_estados_csv))
    if not frames:
        return partial_value * 3.0   # crude fallback: Bim2*0.5 ≈ 1/3 of Q2
    raw = pd.concat(frames)
    bim = raw.groupby(["ano", "bimestre"])["valor_bi"].sum().unstack("bimestre")
    train_yrs = [y for y in train_years if y in bim.index]
    bim2 = bim.loc[train_yrs, 2]
    bim3 = bim.loc[train_yrs, 3]
    ratio = (bim2 * 0.5) / (bim2 * 0.5 + bim3 * 1.0)
    return partial_value / float(ratio.mean())


def build_model_selected(
        best_spec: str,
        estimates: Dict[str, pd.Series],
        indicator_dict: Dict[str, pd.Series],
        cnt_annual: pd.Series,
        cnt_quarterly: pd.Series,
        cl_rmse: float) -> None:
    """
    Produce output/tables/model_selected.csv with hybrid method assignment:
      - Benchmark quarters (annual CNT available): Denton-Cholette (proportional)
      - Nowcast quarters (no annual benchmark yet): ensemble Chow-Lin + Litterman

    Columns: quarter, method, spec, estimate_R_bi, cnt_R_bi, desvio_pct,
             lower_90, upper_90, is_provisional, selection_reason
    """
    denton_key = f"{best_spec}_denton_prop"
    if denton_key not in estimates:
        logger.warning("Denton key %s not found in estimates.", denton_key)
        return

    denton_series = estimates[denton_key]
    train_yrs     = sorted(cnt_annual.index.tolist())

    # ── In-sample rows (Denton-Cholette) ─────────────────────────────────────
    rows = []
    for dt, est_val in denton_series.items():
        act = cnt_quarterly.get(dt)
        dev_pct = ((float(est_val) - float(act)) / float(act) * 100
                   if act is not None and not pd.isna(act) else None)
        rows.append(dict(
            quarter=f"{dt.year}Q{dt.quarter}",
            method="denton_cholette",
            spec=best_spec,
            estimate_R_bi=round(float(est_val), 4),
            cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
            desvio_pct=round(dev_pct, 4) if dev_pct is not None else None,
            lower_90=None,
            upper_90=None,
            is_provisional=False,
            selection_reason="annual CNT benchmark available — Denton-Cholette (parsimonious, no rho)",
        ))

    # ── Nowcast rows (ensemble Chow-Lin + Litterman) ──────────────────────────
    spec_all = indicator_dict.get(best_spec)
    if spec_all is not None:
        nowcast_dates = [dt for dt in spec_all.index if dt.year not in train_yrs]
        if nowcast_dates:
            common_train = sorted(set(spec_all.index.year.unique())
                                  & set(cnt_annual.index.tolist()))
            ind_train = spec_all[spec_all.index.year.isin(common_train)]
            ann_train = cnt_annual.loc[common_train].values

            # Scale partial Q2 if present (Bim3 not yet published)
            ind_extrap_raw = spec_all.loc[nowcast_dates].values.copy()
            extrap_dates   = nowcast_dates

            # Identify 2026Q2 as partial (only 2 out of 6 bimesters of the year)
            partial_mask = [dt.month == 4 and dt.year >= 2026 for dt in extrap_dates]
            for i, (dt, is_partial) in enumerate(zip(extrap_dates, partial_mask)):
                if is_partial:
                    ind_extrap_raw[i] = _scale_partial_q2(best_spec, float(ind_extrap_raw[i]))

            try:
                _, ext_cl = fit_and_extrapolate(ind_train.values, ann_train,
                                                ind_extrap_raw, method="chow_lin")
                _, ext_lt = fit_and_extrapolate(ind_train.values, ann_train,
                                                ind_extrap_raw, method="litterman")
            except Exception as exc:
                logger.warning("Nowcast extrapolation failed: %s", exc)
                ext_cl = ext_lt = np.full(len(extrap_dates), np.nan)

            z90 = 1.645
            for i, dt in enumerate(extrap_dates):
                ensemble = (float(ext_cl[i]) + float(ext_lt[i])) / 2
                lo  = ensemble - z90 * cl_rmse
                hi  = ensemble + z90 * cl_rmse
                act = cnt_quarterly.get(dt)
                dev_pct = ((ensemble - float(act)) / float(act) * 100
                           if act is not None and not pd.isna(act) else None)
                is_partial = partial_mask[i]
                cov_note = (
                    "Bim2 only (Bim3 not yet published; scaled by historical ratio)"
                    if is_partial else
                    "Bim1+Bim2 fully observed"
                )
                rows.append(dict(
                    quarter=f"{dt.year}Q{dt.quarter}",
                    method="ensemble(chow_lin,litterman)",
                    spec=best_spec,
                    estimate_R_bi=round(ensemble, 4),
                    cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
                    desvio_pct=round(dev_pct, 4) if dev_pct is not None else None,
                    lower_90=round(lo, 4),
                    upper_90=round(hi, 4),
                    is_provisional=True,
                    selection_reason=(
                        f"no annual CNT benchmark — ensemble CL+LT extrapolation; "
                        f"indicator: {cov_note}"
                    ),
                ))

    df = (pd.DataFrame(rows)
          .sort_values("quarter")
          .reset_index(drop=True))
    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_TABLES / "model_selected.csv", index=False)
    logger.info("Saved model_selected.csv: %d rows (%d benchmark, %d nowcast)",
                len(df),
                df["method"].eq("denton_cholette").sum(),
                df["method"].ne("denton_cholette").sum())


def run_pipeline(cnt_csv: str = "data/raw/cnt_quarterly.csv",
                 fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Ponto de entrada principal. Requer arquivos CSV reais em data/raw/.
    Ver DATA_ACQUISITION.md para instruções de download.
    """
    logger.info("Carregando dados reais...")
    cnt_quarterly, cnt_annual = load_cnt_real(cnt_csv)
    indicator_dict = load_fiscal_indicators(fiscal_csv)

    logger.info("CNT: %d trimestres | %d anos", len(cnt_quarterly), len(cnt_annual))
    logger.info("Especificações fiscais: %d", len(indicator_dict))

    logger.info("Desagregando...")
    estimates = disaggregate_all(indicator_dict, cnt_annual)

    logger.info("Validando...")
    metrics_df = validate_all(estimates, cnt_quarterly)

    if not metrics_df.empty:
        best = metrics_df.iloc[0]
        logger.info("Melhor modelo: %s | RMSE=%.4f | MAPE=%.2f%% | Corr=%.4f",
                    best["model"], best.get("RMSE", 0),
                    best.get("MAPE", 0), best.get("Corr", 0))

        # ── Hybrid model selection ─────────────────────────────────────────
        best_spec, denton_mape, denton_rmse = select_best_denton_spec(metrics_df)
        logger.info("Best Denton spec: %s | MAPE=%.4f%% | RMSE=%.4f",
                    best_spec, denton_mape, denton_rmse)
        build_model_selected(best_spec, estimates, indicator_dict,
                             cnt_annual, cnt_quarterly, denton_rmse)

        best_series = estimates.get(best["model"])
        if best_series is not None:
            plot_series_comparison(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_pct_errors(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_specification_ranking(metrics_df.reset_index())
            plot_metrics_heatmap(metrics_df.reset_index().head(20))


if __name__ == '__main__':
    run_pipeline()
